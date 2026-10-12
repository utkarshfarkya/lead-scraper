import re

# Georgia is left out: "Tbilisi, Georgia" is the country.
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "hawaii", "idaho", "illinois",
    "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland",
    "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "puerto rico",
}  # fmt: skip

# Cities LinkedIn names US metro areas after ("Greater Boston",
# "Dallas-Fort Worth Metroplex", "San Francisco Bay Area", ...). Names shared
# with big non-US cities (London, Birmingham, Cambridge, ...) are left out.
US_METRO_CITIES = {
    "new york city", "new york", "los angeles", "chicago", "houston", "phoenix",
    "philadelphia", "san antonio", "san diego", "dallas", "fort worth",
    "austin", "san jose", "san francisco", "jacksonville", "columbus",
    "charlotte", "indianapolis", "seattle", "denver", "washington dc",
    "washington", "baltimore", "boston", "nashville", "detroit",
    "oklahoma city", "las vegas", "memphis", "louisville", "milwaukee",
    "albuquerque", "tucson", "fresno", "sacramento", "kansas city", "atlanta",
    "miami", "fort lauderdale", "raleigh", "durham", "chapel hill", "omaha",
    "minneapolis", "st. paul", "tulsa", "cleveland", "tampa", "st. petersburg",
    "st. louis", "pittsburgh", "cincinnati", "orlando", "salt lake city",
    "richmond", "hartford", "buffalo", "rochester", "new orleans", "honolulu",
    "portland", "providence", "greensboro", "charleston", "madison",
    "des moines", "boise", "spokane", "knoxville", "grand rapids", "albany",
    "syracuse", "dayton", "akron", "toledo", "el paso", "bakersfield",
    "riverside", "chattanooga", "savannah", "lexington", "wichita",
    "colorado springs", "harrisburg", "allentown", "new haven", "worcester",
    "little rock", "baton rouge", "tallahassee", "ann arbor", "lansing",
    "fort myers", "sarasota", "reno", "santa barbara", "huntsville", "norfolk",
    "virginia beach", "asheville", "greenville", "anchorage",
}  # fmt: skip

METRO_WORDS = re.compile(r"\b(greater|area|metropolitan|metroplex|metro)\b", re.IGNORECASE)


def is_us_location(location: str) -> bool:
    """Whether a LinkedIn location string is in the United States.

    Handles "Austin, Texas, United States", "Texas, United States",
    "Austin, Texas" and metro names like "Greater Boston".
    """
    loc = location.strip().lower()
    if not loc:
        return False
    if "united states" in loc:
        return True
    if loc.split(",")[-1].strip() in US_STATES:
        return True
    if METRO_WORDS.search(loc):
        core = METRO_WORDS.sub(" ", loc.replace("bay area", ""))
        parts = [p.strip() for p in re.split(r"[-/,]", core)]
        parts = [re.sub(r"\s+", " ", p) for p in parts]
        # "Birmingham, Alabama Metropolitan Area" names the state.
        return any(p in US_METRO_CITIES or p in US_STATES for p in parts)
    return False
