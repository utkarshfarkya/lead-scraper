import random
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from lead_scraper.models import Person, Post
from lead_scraper.portals.base import Portal
from lead_scraper.portals.registry import register

# Persistent browser profile so the LinkedIn login survives between runs.
PROFILE_DIR = Path.home() / ".lead-scraper" / "linkedin-profile"

LOGIN_TIMEOUT_MS = 5 * 60 * 1000

# Caps per post, to keep runs bounded and avoid tripping LinkedIn rate limits.
MAX_REACTORS = 100
MAX_COMMENTERS = 100

# LinkedIn's class names are generated and change constantly, and pages loaded
# from its client-side cache drop the `data-view-name` hooks, so these rely on
# ARIA labels, component keys and visible text. When scraping breaks, update
# these first.
CONTROL_MENU = "button[aria-label^='Open control menu for post']"
PROFILE_LINK = "a[href*='/in/'], a[href*='/company/']"
SELECTORS = {
    "search_input": "input[placeholder='Search']",
    # One search result; the comments render inside it too
    "result": f"[role='listitem']:has({CONTROL_MENU})",
    "control_menu": CONTROL_MENU,
    "profile_link": PROFILE_LINK,
    "commentary": "[data-testid='expandable-text-box']",
    # Comments; replies are comments too
    "comment": "[componentkey^='replaceableComment_']",
    # Reactions popup: each row is labelled "<name> reacted with anything"
    "reactor": "[aria-label*=' reacted with ']",
    # Profile page top card: (name, headline, location, "Contact info")
    "profile_topcard": "[componentkey$='Topcard']",
    # Profile experience page (/in/<id>/details/experience/)
    "experience_section": "[componentkey$='ExperienceDetailsSection']",
}
# Count links under a post. Never click "Open reactions menu": that's the Like picker.
REACTION_COUNT_TEXT = re.compile(r"^[\d,]+ reactions?$")
COMMENT_COUNT_TEXT = re.compile(r"^[\d,]+ comments?$")
MORE_COMMENTS_TEXT = re.compile(r"more comments", re.IGNORECASE)

# Visible <p> texts in an element, minus "• 3rd+" degree lines and "2h"-style
# timestamps, so what's left starts with [name, headline].
P_TEXTS_JS = """e => [...e.querySelectorAll('p')]
    .map(p => p.innerText.trim())
    .filter(t => t && !t.startsWith('•') && !/^\\d+\\s*(s|m|h|d|w|mo|yr)\\b/.test(t))"""

# The post author's name and headline sit in a block around the first profile
# link; walk up until that block contains both.
ACTOR_TEXTS_JS = (
    """e => {
    const texts = """
    + P_TEXTS_JS
    + """;
    for (let node = e, i = 0; i < 8 && node; i++, node = node.parentElement) {
        const found = texts(node);
        if (found.length >= 2) return found;
    }
    return [];
}"""
)

# "Copy link to post" writes to the clipboard; capture it in the page instead
# of touching the user's real clipboard.
CAPTURE_CLIPBOARD_JS = """() => {
    window.__copiedLink = null;
    navigator.clipboard.writeText = text => {
        window.__copiedLink = text;
        return Promise.resolve();
    };
}"""

# Latest role from the experience page. Entries are newest first, in one of
# two shapes:
#   single:  [title, "Company · Full-time", dates, ...]
#   grouped: [company, "Full-time · 4 yrs 10 mos", ...] with the roles in a
#            nested list, newest first.
LATEST_ROLE_JS = """section => {
    const texts = el => [...el.querySelectorAll('p')]
        .map(p => p.innerText.trim()).filter(Boolean);
    const all = texts(section).filter(t => t !== 'Experience');
    if (all.length < 2) return [all[0] || '', ''];
    const durationOnly = /^([A-Za-z-]+ · )?\\d+ (yrs?|mos?)( \\d+ mos?)?$/;
    if (durationOnly.test(all[1])) {
        const role = section.querySelector('ul li');
        return [role ? texts(role)[0] || '' : '', all[0]];
    }
    return [all[0], all[1].split(' · ')[0]];
}"""

# The location is the line just before "· Contact info" in the top card.
LOCATION_JS = """card => {
    const texts = [...card.querySelectorAll('p')]
        .map(p => p.innerText.trim()).filter(t => t && t !== '·');
    const i = texts.indexOf('Contact info');
    return i > 0 ? texts[i - 1] : '';
}"""

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9222


def launch_chrome() -> subprocess.Popen:
    """Start Chrome as a normal process and expose a debugging port.

    Launching through Playwright marks the browser as automated, which makes
    Google refuse "Sign in with Google". A plain Chrome process that Playwright
    attaches to over CDP doesn't carry those flags.
    """
    chrome = subprocess.Popen(
        [
            CHROME_PATH,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version")
            return chrome
        except OSError:
            time.sleep(0.25)
    chrome.terminate()
    raise RuntimeError("Chrome did not start its debugging port in time")


def pause(page: Page, low: float = 1.0, high: float = 2.5) -> None:
    """Random human-ish delay between actions."""
    page.wait_for_timeout(random.uniform(low, high) * 1000)


def text_of(scope: Locator | Page, selector: str) -> str:
    loc = scope.locator(selector).first
    if not loc.count():
        return ""
    return loc.inner_text().strip()


def clean_name(raw: str) -> str:
    """Pull the display name out of LinkedIn's name text.

    'Jane Doe, Open to work Verified Profile 3rd+\\nJane Doe\\n• 3rd+' -> 'Jane Doe'
    'Jane Doe • 3rd+' -> 'Jane Doe'
    """
    lines = [line.strip() for line in raw.splitlines()]
    lines = [line for line in lines if line and not line.startswith("•")]
    if not lines:
        return ""
    # When there's an accessibility label first, the visible name is last.
    return re.sub(r"\s*•.*$", "", lines[-1])


def clean_url(href: str | None) -> str:
    if not href:
        return ""
    parts = urlsplit(urljoin(LinkedInPortal.base_url, href))
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def person_from(texts: list[str], href: str | None) -> Person:
    """Build a Person from [name, ...] texts and a profile link."""
    return Person(name=clean_name(texts[0]) if texts else "", profile_url=clean_url(href))


def unique(people: list[Person]) -> list[Person]:
    seen: set[str] = set()
    result = []
    for person in people:
        key = person.profile_url or person.name
        if key not in seen:
            seen.add(key)
            result.append(person)
    return result


@register
class LinkedInPortal(Portal):
    name = "LinkedIn"
    base_url = "https://www.linkedin.com"
    search_url = f"{base_url}/search/results/content/"

    def build_search_url(self, keywords: list[str]) -> str:
        return f"{self.search_url}?{urlencode({'keywords': ' '.join(keywords)})}"

    def search(self, keywords: list[str], limit: int = 20) -> list[Post]:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            chrome = launch_chrome()
            try:
                browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                page.goto(f"{self.base_url}/feed/")
                self.ensure_logged_in(page)
                self.search_posts(page, keywords)
                posts = self.scrape_results(page, limit)
                # Profiles open in their own tab so the search results stay put.
                self.add_profile_details(context.new_page(), posts)
                browser.close()
            finally:
                chrome.terminate()
        return posts

    def ensure_logged_in(self, page: Page) -> None:
        if "/feed" in page.url:
            return
        print("Please log in to LinkedIn in the opened browser window...")
        page.wait_for_url("**/feed/**", timeout=LOGIN_TIMEOUT_MS)

    def search_posts(self, page: Page, keywords: list[str]) -> None:
        query = " ".join(keywords)
        print(f"Searching LinkedIn posts for: {query}")
        try:
            search_box = page.locator(SELECTORS["search_input"]).first
            search_box.click()
            search_box.fill(query)
            search_box.press("Enter")
            page.wait_for_url("**/search/results/**")
            # The result-type filters ("Posts", "People", ...) are radio buttons.
            page.get_by_role("radio", name="Posts", exact=True).click()
            page.wait_for_url("**/search/results/content/**")
        except PlaywrightTimeoutError:
            # LinkedIn's UI changes often; fall back to the direct posts search URL.
            page.goto(self.build_search_url(keywords))

    def scrape_results(self, page: Page, limit: int) -> list[Post]:
        """Scrape results in place, scrolling to load more until `limit` posts."""
        results = page.locator(SELECTORS["result"])
        try:
            results.first.wait_for(timeout=15000)
        except PlaywrightTimeoutError:
            print("No post results found on the page.")
            return []
        page.evaluate(CAPTURE_CLIPBOARD_JS)

        posts: list[Post] = []
        index = 0
        while len(posts) < limit:
            if not self.load_result(page, results, index):
                break
            result = results.nth(index)
            index += 1
            print(f"[{len(posts) + 1}/{limit}] scraping post")
            try:
                post = self.scrape_post(page, result)
            except PlaywrightError as e:
                print(f"    skipped: {e.message.splitlines()[0]}")
                page.keyboard.press("Escape")
                continue
            print(
                f"    {post.author.name if post.author else '?'}: {len(post.reactors)} reactors, "
                f"{len(post.commenters)} commenters"
            )
            posts.append(post)
            pause(page)
        return posts

    def load_result(self, page: Page, results: Locator, index: int) -> bool:
        """Scroll until result `index` exists. False when no more load."""
        for _ in range(3):
            if results.count() > index:
                return True
            results.last.scroll_into_view_if_needed()
            page.mouse.wheel(0, 3000)
            pause(page, 2, 3)
        return results.count() > index

    def scrape_post(self, page: Page, result: Locator) -> Post:
        result.scroll_into_view_if_needed()
        actor = result.locator(SELECTORS["profile_link"]).first
        author = person_from(actor.evaluate(ACTOR_TEXTS_JS), actor.get_attribute("href"))
        return Post(
            portal=self.name,
            url=self.copy_post_link(page, result),
            author=author,
            content=text_of(result, SELECTORS["commentary"]),
            commenters=self.scrape_commenters(page, result),
            reactors=self.scrape_reactors(page, result),
        )

    def copy_post_link(self, page: Page, result: Locator) -> str:
        page.evaluate("() => { window.__copiedLink = null; }")
        result.locator(SELECTORS["control_menu"]).first.click()
        page.get_by_text("Copy link to post", exact=True).click()
        try:
            page.wait_for_function("() => window.__copiedLink", timeout=3000)
        except PlaywrightTimeoutError:
            return ""
        return page.evaluate("() => window.__copiedLink")

    def scrape_commenters(self, page: Page, result: Locator) -> list[Person]:
        count = result.get_by_text(COMMENT_COUNT_TEXT)
        if not count.count():
            return []
        comments = result.locator(SELECTORS["comment"])
        if not comments.count():
            count.first.click()
            comments.first.wait_for(timeout=10000)

        # "See N more comments" until everything is loaded.
        while comments.count() < MAX_COMMENTERS:
            more = result.get_by_text(MORE_COMMENTS_TEXT)
            if not more.count():
                break
            more.first.click()
            pause(page)

        people = []
        for comment in comments.all()[:MAX_COMMENTERS]:
            link = comment.locator(SELECTORS["profile_link"]).first
            href = link.get_attribute("href") if link.count() else None
            people.append(person_from(comment.evaluate(P_TEXTS_JS), href))
        return unique(people)

    def scrape_reactors(self, page: Page, result: Locator) -> list[Person]:
        count = result.get_by_text(REACTION_COUNT_TEXT)
        if not count.count():
            return []
        count.first.click()
        reactors = page.locator(SELECTORS["reactor"])
        reactors.first.wait_for(timeout=10000)

        # The popup lazy-loads more rows as you scroll to the bottom.
        while reactors.count() < MAX_REACTORS:
            before = reactors.count()
            reactors.last.scroll_into_view_if_needed()
            pause(page)
            if reactors.count() == before:
                break

        people = [
            person_from(row.evaluate(P_TEXTS_JS), row.evaluate("e => e.closest('a')?.href"))
            for row in reactors.all()[:MAX_REACTORS]
        ]
        page.keyboard.press("Escape")
        reactors.first.wait_for(state="detached", timeout=5000)
        return unique(people)

    def add_profile_details(self, page: Page, posts: list[Post]) -> None:
        """Fill in location, position and company from each person's profile,
        and drop people outside `location_filter`."""
        details: dict[str, Person | None] = {}  # None = filtered out
        for person in (p for post in posts for p in post.people()):
            url = person.profile_url
            if url not in details:
                details[url] = self.read_profile(page, person)
            found = details[url]
            if found:
                person.location, person.position, person.company = (
                    found.location,
                    found.position,
                    found.company,
                )

        def keep(person: Person) -> bool:
            return details.get(person.profile_url) is not None

        for post in posts:
            if post.author and not keep(post.author):
                post.author = None
            post.reactors = [p for p in post.reactors if keep(p)]
            post.commenters = [p for p in post.commenters if keep(p)]

    def read_profile(self, page: Page, person: Person) -> Person | None:
        """Location from the profile page; role only if the location passes."""
        url = person.profile_url
        if "/in/" not in url:  # company pages have no location or experience
            return None if self.location_filter else person
        result = Person(name=person.name, profile_url=url)
        try:
            result.location = self.read_location(page, url)
            if self.location_filter and not self.location_filter(result.location):
                print(f"    skip {person.name}: {result.location or 'no location'}")
                return None
            print(f"    {person.name}: {result.location}")
            pause(page, 2, 4)
            result.position, result.company = self.read_latest_role(page, url)
        except PlaywrightError:
            if self.location_filter:
                return None
        pause(page, 2, 4)
        return result

    def read_location(self, page: Page, profile_url: str) -> str:
        page.goto(profile_url)
        card = page.locator(SELECTORS["profile_topcard"]).first
        try:
            card.get_by_text("Contact info", exact=True).wait_for(timeout=10000)
        except PlaywrightTimeoutError:
            return ""
        return card.evaluate(LOCATION_JS)

    def read_latest_role(self, page: Page, profile_url: str) -> tuple[str, str]:
        page.goto(f"{profile_url.rstrip('/')}/details/experience/")
        section = page.locator(SELECTORS["experience_section"]).first
        try:
            section.locator("p").nth(1).wait_for(timeout=10000)
        except PlaywrightTimeoutError:
            return "", ""  # no experience listed, or not visible to us
        position, company = section.evaluate(LATEST_ROLE_JS)
        return position, company
