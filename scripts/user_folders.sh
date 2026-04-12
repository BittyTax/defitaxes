#!/bin/bash

# Configure the folder to analyze
TARGET_DIR="../instance/users"

# Detect OS for stat command compatibility
if [[ "$OSTYPE" == "darwin"* ]]; then
    get_modified() { stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$1"; }
else
    get_modified() { stat -c "%y" "$1" | cut -d'.' -f1 | cut -d' ' -f1,2 | sed 's/ /T/' | cut -c1-16 | sed 's/T/ /'; }
fi

echo ""
echo "=== TEMPORARY / CACHE FILES (excluding db.db) ==="
echo "Last Modified | Size | File Path"
echo "------------------------------------------"

all_found=0
total_kb=0
while IFS= read -r f; do
    all_found=$((all_found + 1))
    size=$(du -sh "$f" 2>/dev/null | cut -f1)
    size_kb=$(du -sk "$f" 2>/dev/null | cut -f1)
    total_kb=$((total_kb + size_kb))
    modified=$(get_modified "$f")
    echo "$modified | $size | $f"
done < <(find "$TARGET_DIR" -type f ! -name "db.db" 2>/dev/null)

if [ "$all_found" -eq 0 ]; then
    echo "None found"
else
    total_mb=$(echo "scale=2; $total_kb / 1024" | bc)
    total_gb=$(echo "scale=2; $total_kb / 1024 / 1024" | bc)
    echo ""
    echo "  Total: $all_found file(s) — ${total_mb} MB (${total_gb} GB)"
    echo ""
    echo -n "  Delete ALL $all_found file(s)? [y/N]: "
    read -r choice < /dev/tty
    if [[ "$choice" =~ ^[yY]$ ]]; then
        find "$TARGET_DIR" -type f ! -name "db.db" -delete
        echo "  Done. Deleted $all_found file(s), freed ${total_mb} MB."
    else
        echo "  Skipped."
    fi
fi