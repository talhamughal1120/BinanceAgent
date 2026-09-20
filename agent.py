import os
import json
import time
import hashlib
import subprocess
import requests
import xml.etree.ElementTree as ET
import re
from html import unescape

# =========================
# SETTINGS
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Works on Windows and GitHub Linux
SKILL_DIR = os.path.join(
    os.path.expanduser("~"),
    ".agents",
    "skills",
    "square-post"
)

HISTORY_FILE = os.path.join(
    BASE_DIR,
    "posted_news.json"
)

RSS_SOURCES = [
    (
        "CoinDesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss/"
    ),
    (
        "Cointelegraph",
        "https://cointelegraph.com/rss"
    ),
]

GEMINI_MODEL = "gemini-3.6-flash"

# OpenAI fallback model
OPENAI_MODEL = "gpt-5.6-luna"

# Broad market coins are used ONLY when
# the article does not contain enough directly
# relevant crypto assets.
BROAD_MARKET_COINS = [
    "$BTC",
    "$ETH",
    "$BNB",
]


# =========================
# LOAD API KEYS
# =========================

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

if not GEMINI_API_KEY and not OPENAI_API_KEY:

    print(
        "❌ GEMINI_API_KEY aur OPENAI_API_KEY dono nahi mili."
    )

    raise SystemExit


# =========================
# NEWS HISTORY
# =========================

def load_history():

    if not os.path.exists(
        HISTORY_FILE
    ):
        return []

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                list
            ):
                return data

            return []

    except Exception:

        return []


def save_history(history):

    history = history[-500:]

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            history,
            f,
            indent=2,
            ensure_ascii=False
        )


def news_id(title):

    return hashlib.sha256(
        title.lower()
        .strip()
        .encode("utf-8")
    ).hexdigest()


# =========================
# TEXT CLEANING
# =========================

def clean_html(text):

    if not text:
        return ""

    text = unescape(text)

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================
# RSS NEWS
# =========================

def fetch_rss(
    source_name,
    url
):

    try:

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        articles = []

        for item in root.findall(
            ".//item"
        )[:10]:

            title = item.findtext(
                "title",
                ""
            ).strip()

            link = item.findtext(
                "link",
                ""
            ).strip()

            description = item.findtext(
                "description",
                ""
            ).strip()

            description = clean_html(
                description
            )

            if title and link:

                articles.append({
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "description": description
                })

        print(
            f"{source_name}: {len(articles)} articles"
        )

        return articles

    except Exception as e:

        print(
            f"❌ {source_name} error:",
            e
        )

        return []


def get_news():

    all_articles = []

    for source_name, url in RSS_SOURCES:

        articles = fetch_rss(
            source_name,
            url
        )

        all_articles.extend(
            articles
        )

    return all_articles


# =========================
# REMOVE EXACT DUPLICATES
# =========================

def remove_duplicates(
    articles
):

    seen = set()

    unique = []

    for article in articles:

        article_id = news_id(
            article["title"]
        )

        if article_id not in seen:

            seen.add(
                article_id
            )

            unique.append(
                article
            )

    return unique


# =========================
# TOPIC SIMILARITY
# =========================

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "after",
    "over",
    "under",
    "about",
    "could",
    "would",
    "should",
    "will",
    "have",
    "has",
    "been",
    "are",
    "was",
    "were",
    "its",
    "their",
    "they",
    "than",
    "what",
    "how",
    "why",
    "who",
    "new",
    "news",
    "says",
    "said",
    "according",
    "latest",
    "report",
    "reports",
    "amid",
    "more"
}


def title_words(title):

    words = re.findall(
        r"[a-zA-Z0-9]+",
        title.lower()
    )

    return {
        word
        for word in words
        if len(word) >= 4
        and word not in STOP_WORDS
    }


def topic_similarity(
    title1,
    title2
):

    words1 = title_words(
        title1
    )

    words2 = title_words(
        title2
    )

    if not words1 or not words2:
        return 0

    intersection = (
        words1.intersection(
            words2
        )
    )

    smaller = min(
        len(words1),
        len(words2)
    )

    if smaller == 0:
        return 0

    return (
        len(intersection)
        / smaller
    )


def is_same_topic(
    article,
    recent_articles
):

    current_title = article[
        "title"
    ]

    for old_article in recent_articles[-30:]:

        if isinstance(
            old_article,
            dict
        ):

            old_title = old_article.get(
                "title",
                ""
            )

        else:

            continue

        if not old_title:
            continue

        similarity = topic_similarity(
            current_title,
            old_title
        )

        if similarity >= 0.60:

            print(
                "⏭️ Same/similar topic skipped:"
            )

            print(
                "   Current:",
                current_title
            )

            print(
                "   Previous:",
                old_title
            )

            return True

    return False


# =========================
# ARTICLE CONTENT
# =========================

def get_article_context(
    article
):

    title = article.get(
        "title",
        ""
    )

    description = article.get(
        "description",
        ""
    )

    source = article.get(
        "source",
        ""
    )

    link = article.get(
        "link",
        ""
    )

    context = f"""
SOURCE: {source}

TITLE:
{title}

ARTICLE DESCRIPTION:
{description}

ORIGINAL LINK:
{link}
"""

    return context


# =========================
# COIN / CASHTAG DETECTION
# =========================

COIN_MAP = {

    "bitcoin": "$BTC",
    "btc": "$BTC",

    "ethereum": "$ETH",
    "ether": "$ETH",
    "eth": "$ETH",

    "bnb": "$BNB",
    "binance coin": "$BNB",

    "xrp": "$XRP",
    "ripple": "$XRP",

    "dogecoin": "$DOGE",
    "doge": "$DOGE",

    "solana": "$SOL",
    "sol": "$SOL",

    "cardano": "$ADA",
    "ada": "$ADA",

    "chainlink": "$LINK",
    "link": "$LINK",

    "avalanche": "$AVAX",
    "avax": "$AVAX",

    "polygon": "$POL",
    "matic": "$MATIC",

    "tron": "$TRX",
    "trx": "$TRX",

    "sui": "$SUI",

    "toncoin": "$TON",
    "ton": "$TON",

    "shiba inu": "$SHIB",
    "shiba": "$SHIB",
    "shib": "$SHIB",

    "pepe": "$PEPE",

    "aptos": "$APT",
    "apt": "$APT",

    "arbitrum": "$ARB",
    "arb": "$ARB",

    "optimism": "$OP",
    "op": "$OP",

    "uniswap": "$UNI",
    "uni": "$UNI",

    "aave": "$AAVE",

    "cosmos": "$ATOM",
    "atom": "$ATOM",

    "near": "$NEAR",

    "render": "$RENDER",
    "rndr": "$RENDER",

    "ondo": "$ONDO",

    "stellar": "$XLM",
    "xlm": "$XLM",

    "hedera": "$HBAR",
    "hbar": "$HBAR",

    "polkadot": "$DOT",
    "dot": "$DOT",
}


def detect_relevant_coins(
    article
):

    text = (
        article.get(
            "title",
            ""
        )
        + " "
        + article.get(
            "description",
            ""
        )
    ).lower()

    found = []

    for name in sorted(
        COIN_MAP.keys(),
        key=len,
        reverse=True
    ):

        if re.search(
            r"\b"
            + re.escape(name)
            + r"\b",
            text
        ):

            coin = COIN_MAP[
                name
            ]

            if coin not in found:

                found.append(
                    coin
                )

    return found


# =========================
# AI PROMPT
# =========================

def build_prompt(
    article
):

    article_context = get_article_context(
        article
    )

    relevant_coins = detect_relevant_coins(
        article
    )

    if relevant_coins:

        relevant_text = ", ".join(
            relevant_coins[:5]
        )

    else:

        relevant_text = (
            "No specific crypto asset detected."
        )

    prompt = f"""
You are a professional crypto news writer for Binance Square.

Create ONE high-quality Binance Square news post.

Your job is to explain ONLY what is supported by the
provided article title and article description.

Do NOT invent information.

=========================
ARTICLE INFORMATION
=========================

{article_context}

Potentially detected crypto assets:
{relevant_text}

=========================
CASHTAG RULES
=========================

The final post MUST contain exactly 3 Binance-style
dollar cashtags.

ALL 3 cashtags MUST appear on the FIRST LINE.

Example:

$XRP $BTC $ETH

IMPORTANT:

1. Use the most relevant crypto assets connected to the article.

2. If the article directly mentions multiple crypto assets,
prioritize those assets.

3. Do NOT use random coins just to increase engagement.

4. If the article directly mentions only one or two coins,
you may use BTC, ETH or BNB as broad market-context
cashtags ONLY when the article is clearly related to
the broader crypto market, regulation, adoption,
blockchain infrastructure or digital assets.

5. Never claim that a backup/broad-market coin was mentioned
in the article if it was not mentioned.

6. Do NOT put any dollar cashtag anywhere else in the post.

7. Do NOT use dollar cashtags inside normal hashtags.

8. Cashtags must be uppercase.

=========================
HEADLINE
=========================

Create a strong, professional headline.

The headline must be factual.

Do NOT use clickbait.

Do NOT exaggerate.

Do NOT create information that is not supported
by the article.

=========================
BODY
=========================

Write 2 to 4 short paragraphs.

Keep paragraphs easy to read on mobile.

Explain the actual news first.

Use simple professional language.

Do not repeat the same sentence in different words.

=========================
WHY IT MATTERS
=========================

Include exactly this section:

**Why It Matters**

Then explain why the reported development
could matter to the crypto/blockchain market.

If the article does not provide enough information
to explain a specific impact, keep this section
careful and general.

Do not invent market reactions.

Do not invent investor behavior.

Do not invent price effects.

=========================
OPINIONS
=========================

If the article contains an analyst's,
company's, executive's or other person's opinion,
clearly attribute it.

Examples:

"Analysts said..."

"The company said..."

"According to..."

Do NOT turn an opinion into an established fact.

=========================
NUMBERS
=========================

Use statistics, percentages, prices, dates,
amounts or other numbers ONLY if they are
supported by the provided article information.

Never invent numbers.

Never create estimated numbers.

Never create fake statistics.

=========================
QUESTION
=========================

At the end, ask exactly ONE genuine,
natural question related to the news.

Do not ask a generic spam question.

=========================
SOURCE
=========================

Include:

Source: ORIGINAL_URL

Use the exact original URL supplied above.

=========================
HASHTAGS
=========================

At the very end use 3 to 5 relevant normal hashtags.

Examples:

#CryptoNews
#Bitcoin
#Blockchain
#DigitalAssets

Do NOT put $cashtags here.

=========================
STRICT SAFETY / QUALITY RULES
=========================

Never use:

"Buy now"

"Sell now"

"100x guaranteed"

"Guaranteed profit"

"Guaranteed returns"

"Risk-free"

"Easy money"

"Get rich"

"Moon guaranteed"

"Profit guaranteed"

"Will definitely pump"

"Will definitely dump"

Any language promising a certain financial result.

Do not give direct financial advice.

Do not manipulate readers into trading.

Do not use fake urgency.

Do not invent facts.

Do not invent statistics.

Do not invent quotes.

Do not invent partnerships.

Do not invent regulatory decisions.

Do not invent price targets.

Do not invent market reactions.

Do not claim a person said something unless
the article information supports it.

Do not present analyst opinions as facts.

Do not use information that is not supported
by the supplied article.

=========================
FINAL FORMAT
=========================

$COIN1 $COIN2 $COIN3

**Strong Factual Headline**

Paragraph 1.

Paragraph 2.

Paragraph 3 if needed.

**Why It Matters**

Short explanation.

One genuine question?

Source: ORIGINAL_URL

#RelevantHashtag #CryptoNews #Blockchain

Return ONLY the final post.
"""

    return prompt


# =========================
# GEMINI AI
# =========================

def generate_with_gemini(
    prompt
):

    if not GEMINI_API_KEY:

        print(
            "⚠️ GEMINI_API_KEY available nahi."
        )

        return None

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )

    payload = {

        "contents": [

            {

                "parts": [

                    {
                        "text": prompt
                    }

                ]

            }

        ]

    }

    for attempt in range(
        1,
        4
    ):

        try:

            print(
                f"Gemini attempt {attempt}/3..."
            )

            response = requests.post(
                url,
                json=payload,
                timeout=60
            )

            # Temporary server busy
            if response.status_code == 503:

                print(
                    "⚠️ Gemini busy. 5 seconds wait..."
                )

                time.sleep(5)

                continue

            # Quota exceeded
            if response.status_code == 429:

                print(
                    "⚠️ Gemini quota/rate limit reached."
                )

                return None

            if response.status_code != 200:

                print(
                    "❌ Gemini error:"
                )

                print(
                    response.text
                )

                return None

            data = response.json()

            candidates = data.get(
                "candidates",
                []
            )

            if not candidates:

                print(
                    "❌ Gemini ne koi candidate return nahi ki."
                )

                return None

            parts = candidates[0].get(
                "content",
                {}
            ).get(
                "parts",
                []
            )

            if not parts:

                print(
                    "❌ Gemini response empty hai."
                )

                return None

            post = parts[0].get(
                "text",
                ""
            ).strip()

            if post:

                print(
                    "✅ Gemini se post generate ho gayi."
                )

                return post

            return None

        except Exception as e:

            print(
                "❌ Gemini exception:",
                e
            )

            if attempt < 3:

                time.sleep(5)

    return None


# =========================
# OPENAI FALLBACK
# =========================

def generate_with_openai(
    prompt
):

    if not OPENAI_API_KEY:

        print(
            "❌ OPENAI_API_KEY available nahi."
        )

        return None

    print(
        f"OpenAI fallback: {OPENAI_MODEL}"
    )

    url = (
        "https://api.openai.com/v1/responses"
    )

    headers = {

        "Authorization":
            f"Bearer {OPENAI_API_KEY}",

        "Content-Type":
            "application/json"

    }

    payload = {

        "model":
            OPENAI_MODEL,

        "input":
            prompt,

        "max_output_tokens":
            1200

    }

    for attempt in range(
        1,
        3
    ):

        try:

            print(
                f"OpenAI attempt {attempt}/2..."
            )

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=90
            )

            if response.status_code in (
                429,
                500,
                502,
                503,
                504
            ):

                print(
                    "⚠️ OpenAI temporary error:"
                    f" {response.status_code}"
                )

                if attempt < 2:

                    time.sleep(5)

                    continue

            if response.status_code != 200:

                print(
                    "❌ OpenAI error:"
                )

                print(
                    response.text
                )

                return None

            data = response.json()

            # Responses API output_text
            post = data.get(
                "output_text",
                ""
            ).strip()

            # Fallback parser in case
            # output_text is not present.
            if not post:

                output = data.get(
                    "output",
                    []
                )

                collected = []

                for item in output:

                    if item.get(
                        "type"
                    ) != "message":

                        continue

                    for content in item.get(
                        "content",
                        []
                    ):

                        if content.get(
                            "type"
                        ) == "output_text":

                            text = content.get(
                                "text",
                                ""
                            )

                            if text:
                                collected.append(
                                    text
                                )

                post = "\n".join(
                    collected
                ).strip()

            if post:

                print(
                    "✅ OpenAI se post generate ho gayi."
                )

                return post

            print(
                "❌ OpenAI response empty hai."
            )

            return None

        except Exception as e:

            print(
                "❌ OpenAI exception:",
                e
            )

            if attempt < 2:

                time.sleep(5)

    return None


# =========================
# AI GENERATION
# =========================

def generate_post(
    article
):

    prompt = build_prompt(
        article
    )

    # ---------------------------------
    # FIRST: GEMINI
    # ---------------------------------

    post = generate_with_gemini(
        prompt
    )

    if post:

        return post

    # ---------------------------------
    # SECOND: OPENAI FALLBACK
    # ---------------------------------

    print(
        "\n🔄 Gemini failed."
    )

    print(
        "🔄 OpenAI fallback start ho raha hai..."
    )

    post = generate_with_openai(
        prompt
    )

    if post:

        return post

    print(
        "❌ Gemini aur OpenAI dono se post generate nahi hui."
    )

    return None


# =========================
# BLOCKED LANGUAGE
# =========================

BLOCKED_PHRASES = [

    "buy now",
    "sell now",

    "100x guaranteed",
    "100x guarantee",

    "guaranteed profit",
    "guaranteed profits",

    "guaranteed return",
    "guaranteed returns",

    "risk-free",
    "risk free",

    "easy money",
    "get rich",

    "profit guaranteed",
    "returns guaranteed",

    "moon guaranteed",
    "will definitely pump",
    "will definitely dump",

]


def contains_blocked_language(
    post
):

    lower_post = post.lower()

    for phrase in BLOCKED_PHRASES:

        if phrase in lower_post:

            return True, phrase

    return False, None


# =========================
# REMOVE MARKDOWN HEADERS
# =========================

def clean_generated_post(
    post
):

    post = post.strip()

    post = re.sub(
        r"^```(?:text|markdown)?",
        "",
        post,
        flags=re.IGNORECASE
    )

    post = re.sub(
        r"```$",
        "",
        post,
        flags=re.IGNORECASE
    )

    return post.strip()


# =========================
# CASHTAG CHECK / FIX
# =========================

def fix_cashtags(
    post,
    article
):

    found = re.findall(
        r"\$[A-Za-z]{2,10}\b",
        post
    )

    cashtags = []

    for coin in found:

        coin = coin.upper()

        if coin not in cashtags:

            cashtags.append(
                coin
            )

    article_coins = detect_relevant_coins(
        article
    )

    final_coins = []

    # First: article-related coins
    for coin in article_coins:

        if coin not in final_coins:

            final_coins.append(
                coin
            )

        if len(final_coins) == 3:

            break

    # Second: generated coins
    for coin in cashtags:

        if coin not in final_coins:

            final_coins.append(
                coin
            )

        if len(final_coins) == 3:

            break

    # Third: broad market
    for coin in BROAD_MARKET_COINS:

        if coin not in final_coins:

            final_coins.append(
                coin
            )

        if len(final_coins) == 3:

            break

    final_coins = final_coins[:3]

    # Remove every existing cashtag
    clean_post = re.sub(
        r"\$[A-Za-z]{2,10}\b\s*",
        "",
        post
    ).strip()

    lines = clean_post.splitlines()

    if lines:

        first_line = lines[0].strip()

        if re.fullmatch(
            r"(?:#?\$?[A-Za-z0-9]+\s*){2,}",
            first_line
        ):

            if "$" in first_line:

                lines = lines[1:]

    clean_post = "\n".join(
        lines
    ).strip()

    final_post = (
        " ".join(final_coins)
        + "\n\n"
        + clean_post
    )

    return final_post


# =========================
# VALIDATE POST
# =========================

def validate_post(
    post
):

    errors = []

    # ---------------------------------
    # Cashtag count
    # ---------------------------------

    cashtags = re.findall(
        r"\$[A-Za-z]{2,10}\b",
        post
    )

    unique_cashtags = []

    for coin in cashtags:

        coin = coin.upper()

        if coin not in unique_cashtags:

            unique_cashtags.append(
                coin
            )

    if len(unique_cashtags) != 3:

        errors.append(
            "Exactly 3 unique cashtags required."
        )

    # ---------------------------------
    # First line
    # ---------------------------------

    lines = post.splitlines()

    if not lines:

        errors.append(
            "Post is empty."
        )

        return errors

    first_line = lines[0]

    first_line_tags = re.findall(
        r"\$[A-Za-z]{2,10}\b",
        first_line
    )

    if len(first_line_tags) != 3:

        errors.append(
            "All 3 cashtags must be on first line."
        )

    # ---------------------------------
    # No cashtags after first line
    # ---------------------------------

    body = "\n".join(
        lines[1:]
    )

    if re.search(
        r"\$[A-Za-z]{2,10}\b",
        body
    ):

        errors.append(
            "Cashtag found outside first line."
        )

    # ---------------------------------
    # Blocked language
    # ---------------------------------

    blocked, phrase = contains_blocked_language(
        post
    )

    if blocked:

        errors.append(
            f"Blocked language found: {phrase}"
        )

    # ---------------------------------
    # Required sections
    # ---------------------------------

    if "Why It Matters" not in post:

        errors.append(
            "Missing Why It Matters section."
        )

    if "Source:" not in post:

        errors.append(
            "Missing Source."
        )

    # ---------------------------------
    # Normal hashtags
    # ---------------------------------

    hashtags = re.findall(
        r"#[A-Za-z][A-Za-z0-9_]*",
        post
    )

    if len(hashtags) < 3:

        errors.append(
            "At least 3 normal hashtags required."
        )

    if len(hashtags) > 5:

        errors.append(
            "Maximum 5 normal hashtags allowed."
        )

    # ---------------------------------
    # Dangerous patterns
    # ---------------------------------

    dangerous_patterns = [

        r"guaranteed\s+profit",
        r"guaranteed\s+return",
        r"profit\s+guaranteed",
        r"100\s*x\s+guaranteed",
        r"risk[- ]free",
        r"buy\s+now",
        r"sell\s+now",

    ]

    lower_post = post.lower()

    for pattern in dangerous_patterns:

        if re.search(
            pattern,
            lower_post
        ):

            errors.append(
                f"Unsafe financial phrase: {pattern}"
            )

    return errors


# =========================
# PUBLISH TO BINANCE SQUARE
# =========================

def publish_to_binance(
    post
):

    print(
        "\nPublishing to Binance Square..."
    )

    try:

        result = subprocess.run(
            [
                "node",
                "scripts/post-text.mjs",
                "--text",
                post
            ],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:

            print(
                "❌ Binance publish failed:"
            )

            print(
                result.stderr
            )

            return False

        print(
            result.stdout
        )

        return True

    except Exception as e:

        print(
            "❌ Binance publishing error:"
        )

        print(e)

        return False


# =========================
# SELECT BEST NEW ARTICLE
# =========================

def select_article(
    articles,
    history
):

    posted_ids = set()

    recent_articles = []

    for item in history:

        if isinstance(
            item,
            str
        ):

            posted_ids.add(
                item
            )

        elif isinstance(
            item,
            dict
        ):

            item_id = item.get(
                "id"
            )

            if item_id:

                posted_ids.add(
                    item_id
                )

            recent_articles.append(
                item
            )

    candidates = []

    for article in articles:

        article_id = news_id(
            article["title"]
        )

        if article_id in posted_ids:

            continue

        if is_same_topic(
            article,
            recent_articles
        ):

            continue

        candidates.append(
            article
        )

    return candidates


# =========================
# SAVE MODERN HISTORY
# =========================

def add_to_history(
    history,
    article
):

    article_id = news_id(
        article["title"]
    )

    history.append({

        "id":
            article_id,

        "title":
            article["title"],

        "source":
            article["source"],

        "link":
            article["link"],

        "posted_at":
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

    })

    save_history(
        history
    )


# =========================
# MAIN
# =========================

def main():

    print("=" * 60)

    print(
        "🚀 Binance Square AI News Agent"
    )

    print("=" * 60)

    history = load_history()

    print(
        f"Previous posts in history: {len(history)}"
    )

    # ---------------------------------
    # Fetch news
    # ---------------------------------

    articles = get_news()

    print(
        f"Total articles: {len(articles)}"
    )

    # ---------------------------------
    # Remove duplicates
    # ---------------------------------

    articles = remove_duplicates(
        articles
    )

    print(
        f"Unique articles: {len(articles)}"
    )

    # ---------------------------------
    # Find fresh topics
    # ---------------------------------

    new_articles = select_article(
        articles,
        history
    )

    print(
        f"New/unposted articles: {len(new_articles)}"
    )

    if not new_articles:

        print(
            "ℹ️ Koi suitable new/different news nahi mili."
        )

        return

    # ---------------------------------
    # Select article
    # ---------------------------------

    article = new_articles[0]

    print(
        "\nSelected news:"
    )

    print(
        article["title"]
    )

    print(
        "Source:",
        article["source"]
    )

    # ---------------------------------
    # Generate post
    # ---------------------------------

    post = generate_post(
        article
    )

    if not post:

        print(
            "❌ Post generate nahi hui."
        )

        return

    # ---------------------------------
    # Clean AI output
    # ---------------------------------

    post = clean_generated_post(
        post
    )

    # ---------------------------------
    # Fix cashtags
    # ---------------------------------

    post = fix_cashtags(
        post,
        article
    )

    # ---------------------------------
    # Validate
    # ---------------------------------

    validation_errors = validate_post(
        post
    )

    if validation_errors:

        print(
            "\n❌ Post validation failed:"
        )

        for error in validation_errors:

            print(
                " -",
                error
            )

        print(
            "\nPost publish nahi ki gayi."
        )

        return

    # ---------------------------------
    # Show final post
    # ---------------------------------

    print(
        "\n"
        + "=" * 60
    )

    print(
        "GENERATED POST"
    )

    print(
        "=" * 60
    )

    print(
        post
    )

    print(
        "=" * 60
    )

    # ---------------------------------
    # Publish
    # ---------------------------------

    success = publish_to_binance(
        post
    )

    if success:

        add_to_history(
            history,
            article
        )

        print(
            "\n✅ Binance Square post successfully publish ho gayi!"
        )

        print(
            "✅ News history saved."
        )

    else:

        print(
            "\n❌ Post publish nahi hui."
        )

        print(
            "News history mein save nahi ki gayi."
        )


# =========================
# START
# =========================

if __name__ == "__main__":

    main()
