#!/usr/bin/env bash
#
# Premarket gappers scanner.
#
# Design note: the original spec called for WebFetch(url, prompt) as the data
# source. WebFetch is a Claude-agent tool (it fetches a page and runs an AI
# model over it) and cannot be invoked from a standalone shell script. This
# script substitutes:
#   - Yahoo Finance's own (unofficial, undocumented) screener JSON API —
#     the same endpoint https://finance.yahoo.com/markets/stocks/gainers/
#     calls client-side to populate its table — instead of scraping that
#     page's rendered HTML. The initial HTML response only contains a
#     "Trending Tickers" sidebar widget (mixed gainers/losers/crypto, no
#     volume field), not the actual gainers table, which loads via this API
#     after page hydration. Hitting it directly gives real structured JSON
#     (symbol, price, % change, volume, market cap) in a single request, no
#     API key required.
#   - A direct curl call to the Anthropic Messages API for the one-sentence
#     catalyst summary, grounded in scraped Benzinga quote-page text (so the
#     model summarizes real scraped text rather than inventing news from a
#     bare ticker symbol).
#
# Required environment variable (must already be set — this script does not
# prompt for or store any credentials):
#   ANTHROPIC_API_KEY   - Anthropic API key
#
# Caveats:
#   - The Yahoo screener endpoint is unofficial/undocumented. It works
#     without a "crumb"/cookie handshake as of this writing but Yahoo has
#     tightened access to these endpoints before and may again — if it
#     starts returning errors or empty results, that's the likely cause.
#   - "premarket_volume" is sourced from Yahoo's regularMarketVolume field,
#     which reflects premarket volume only while premarket trading is
#     actually in progress. Outside that window it's just current volume.
#   - "gap_pct" is Yahoo's regularMarketChangePercent (change vs previous
#     close), which is the standard definition of a price "gap."
#   - Benzinga scraping is best-effort (page structure/anti-bot behavior can
#     change); on failure catalyst=null and headlines=[] for that ticker,
#     per spec, and the scan continues.
#
# Usage:
#   ANTHROPIC_API_KEY=... ./premarket_gappers.sh

set -uo pipefail

# ---- Load .env if present (ANTHROPIC_API_KEY) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +a
fi

# ---- Config ----
DATE="$(date +%Y-%m-%d)"
OUTFILE="./premarket_gappers_${DATE}.json"
YAHOO_SCREENER_URL="https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds=day_gainers&count=100"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
GAP_MIN=5
PRICE_MIN=3
VOL_MIN=50000
CLAUDE_MODEL="claude-sonnet-5"

# ---- Pre-flight checks ----
for bin in curl jq python; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: $bin is required but not found on PATH" >&2; exit 1; }
done
: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY env var}"

SCANNED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# ---- Step 1: fetch gainers screener & filter in one pass ----
echo "Fetching Yahoo day_gainers screener..." >&2
screener_json="$(curl -s --max-time 15 -A "$UA" "$YAHOO_SCREENER_URL" || true)"

result_type="$(echo "$screener_json" | jq -r '.finance.result | type' 2>/dev/null || echo "invalid")"
if [ "$result_type" != "array" ]; then
  echo "ERROR: Yahoo screener endpoint did not return usable data. Raw response:" >&2
  echo "$screener_json" | head -c 1000 >&2
  echo "" >&2
  exit 1
fi

top10="$(echo "$screener_json" | jq -c --argjson gmin "$GAP_MIN" --argjson pmin "$PRICE_MIN" --argjson vmin "$VOL_MIN" '
  .finance.result[0].quotes
  | map({
      symbol: .symbol,
      price: .regularMarketPrice,
      gap_pct: (((.regularMarketChangePercent // 0) * 100 | round) / 100),
      premarket_volume: .regularMarketVolume
    })
  | map(select(.price != null and .premarket_volume != null))
  | map(select(.gap_pct > $gmin and .price > $pmin and .premarket_volume > $vmin))
  | sort_by(-.gap_pct)
  | .[:10]
')"

count="$(echo "$top10" | jq 'length')"
if [ "$count" -eq 0 ]; then
  echo "No tickers matched the filters today." >&2
  jq -n --arg scanned_at "$SCANNED_AT" '{scanned_at:$scanned_at, gappers:[]}' > "$OUTFILE"
  echo "Premarket Gappers: 0 names. Top: (none)"
  exit 0
fi

# ---- Step 2: catalyst lookup per ticker (Benzinga scrape -> Claude summary) ----
#
# IMPORTANT: nothing containing scraped or model-generated text is ever
# passed to jq/curl as a command-line argument (--arg/--argjson/-d "$var").
# On Windows/Git Bash, passing large and/or non-ASCII strings as argv to a
# native binary can corrupt multi-byte UTF-8 (curly quotes, em-dashes, "™",
# etc. are common in scraped news text) and/or hit the ~8KB command-line
# length limit — both were observed causing silent failures here. Every
# such value is instead written to a temp file and read back with
# --rawfile/--slurpfile/@file, which go through normal file I/O instead of
# argv and have neither problem. Only short, guaranteed-ASCII values (ticker
# symbols, numbers) use --arg/--argjson directly.

entries_dir="$(mktemp -d)"
rank=1
for row in $(echo "$top10" | jq -c '.[]'); do
  sym="$(echo "$row" | jq -r '.symbol')"
  price="$(echo "$row" | jq -r '.price')"
  gap_pct="$(echo "$row" | jq -r '.gap_pct')"
  vol="$(echo "$row" | jq -r '.premarket_volume')"

  echo "Looking up catalyst for $sym ($rank/$count)..." >&2

  catalyst_file="$(mktemp)"
  headlines_file="$(mktemp)"
  echo "null" > "$catalyst_file"
  echo "[]" > "$headlines_file"

  page_text_file="$(mktemp)"
  curl -s --max-time 10 -A "$UA" "https://www.benzinga.com/quote/${sym}" 2>/dev/null | python -c '
import sys, html, re
raw = sys.stdin.read()
raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.S|re.I)
raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.S|re.I)
text = re.sub("<[^<]+?>", " ", raw)
text = html.unescape(text)
text = re.sub(r"\s+", " ", text).strip()
idx = text.find("Press Releases")
snippet = text[idx:] if idx != -1 else text
sys.stdout.write(snippet[:6000])
' > "$page_text_file" 2>/dev/null || true

  page_text_len="$(wc -c < "$page_text_file" | tr -d '[:space:]')"

  if [ -n "$page_text_len" ] && [ "$page_text_len" -gt 200 ]; then
    payload_file="$(mktemp)"
    jq -n --rawfile pagetext "$page_text_file" --arg symbol "$sym" --arg model "$CLAUDE_MODEL" '
      {
        model: $model,
        max_tokens: 300,
        messages: [{
          role: "user",
          content: ("What recent news or catalyst is driving " + $symbol + " stock today? Return a one-sentence summary, then up to 2 recent headlines verbatim. Just the data — no commentary. Base your answer ONLY on the scraped page text below; if it contains no clear news/catalyst, say plainly that none was found rather than inventing one.\n\nPAGE TEXT:\n" + $pagetext)
        }]
      }' > "$payload_file"

    response_file="$(mktemp)"
    curl -s --max-time 20 https://api.anthropic.com/v1/messages \
      -H "x-api-key: ${ANTHROPIC_API_KEY}" \
      -H "anthropic-version: 2023-06-01" \
      -H "content-type: application/json" \
      --data @"$payload_file" > "$response_file" 2>/dev/null || true
    rm -f "$payload_file"

    summary_text_file="$(mktemp)"
    jq -r '.content[0].text // empty' "$response_file" > "$summary_text_file" 2>/dev/null || true
    rm -f "$response_file"

    summary_len="$(wc -c < "$summary_text_file" | tr -d '[:space:]')"
    if [ -n "$summary_len" ] && [ "$summary_len" -gt 0 ]; then
      sed -n '1p' "$summary_text_file" | sed 's/^[- ]*//' | jq -R -s 'if length==0 then null else rtrimstr("\n") end' > "$catalyst_file"
      tail -n +2 "$summary_text_file" | grep -v '^[[:space:]]*$' | sed 's/^[-•0-9. ]*//' | jq -R . | jq -s '.[:2]' > "$headlines_file" 2>/dev/null || echo '[]' > "$headlines_file"
    fi
    rm -f "$summary_text_file"
  fi
  rm -f "$page_text_file"

  jq -n --argjson rank "$rank" --arg symbol "$sym" --argjson price "$price" \
    --argjson gap_pct "$gap_pct" --argjson volume "$vol" \
    --slurpfile catalyst "$catalyst_file" --slurpfile headlines "$headlines_file" \
    '{rank:$rank, symbol:$symbol, price:$price, gap_pct:$gap_pct, premarket_volume:$volume, catalyst:$catalyst[0], headlines:$headlines[0]}' \
    > "$entries_dir/$(printf '%03d' "$rank").json"

  rm -f "$catalyst_file" "$headlines_file"
  rank=$((rank+1))
  sleep 0.3
done

combined_file="$(mktemp)"
jq -s '.' "$entries_dir"/*.json > "$combined_file"
jq -n --arg scanned_at "$SCANNED_AT" --slurpfile gappers "$combined_file" '{scanned_at:$scanned_at, gappers:$gappers[0]}' > "$OUTFILE"
rm -rf "$entries_dir" "$combined_file"

echo "Saved: $OUTFILE" >&2

# ---- Summary line (read back from the file we just wrote, not a bash var) ----
top3="$(jq -r '.gappers[:3] | map("\(.symbol) (\(.gap_pct)%) — \(.catalyst // "no catalyst found")") | join(", ")' "$OUTFILE")"
total="$(jq '.gappers | length' "$OUTFILE")"
echo "Premarket Gappers: ${total} names. Top: ${top3}"
