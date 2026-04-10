#!/bin/bash

# Configure the folder to analyze and number of items to show
TARGET_DIR="../instance/users"
NUM_ITEMS="${1:-10}"

echo "=== TOP $NUM_ITEMS LARGEST FOLDERS in $TARGET_DIR ==="
echo "Size | Folder Path"
echo "-----+------------------------------------------"
du -h -d 1 "$TARGET_DIR" 2>/dev/null | sort -hr | head -$NUM_ITEMS

echo ""
echo "=== TOP $NUM_ITEMS OLDEST UNCHANGED FOLDERS in $TARGET_DIR ==="
echo "Last Modified | Size | Folder Path"
echo "--------------+------+------------------------------------------"
total_kb=0
find "$TARGET_DIR" -type d -mindepth 1 -maxdepth 1 2>/dev/null | while read dir; do
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    size_kb=$(du -sk "$dir" 2>/dev/null | cut -f1)
    modified=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$dir")
    echo "$modified|$size|$dir|$size_kb"
done | sort | head -$NUM_ITEMS | tee /tmp/oldest_folders.tmp | column -t -s '|' | cut -d'|' -f1-3

echo ""
echo "=== TOTAL SIZE OF TOP $NUM_ITEMS OLDEST FOLDERS ==="
total_kb=$(awk -F'|' '{sum += $4} END {print sum}' /tmp/oldest_folders.tmp)
total_mb=$((total_kb / 1024))
total_gb=$(echo "scale=2; $total_kb / 1024 / 1024" | bc)
echo "Total: ${total_mb} MB (${total_gb} GB)"
rm -f /tmp/oldest_folders.tmp

echo ""
echo "=== FOLDERS CONTAINING transactions.csv ==="
echo "Folder Path"
echo "------------------------------------------"
found_csv=0
find "$TARGET_DIR" -type f -name "transactions.csv" 2>/dev/null | while read f; do
    dirname "$f"
    found_csv=1
done
if [ $found_csv -eq 0 ]; then
    echo "None found"
fi

echo ""
echo "=== FOLDERS CONTAINING NON-STANDARD SQL FILES (not db.db) ==="
echo "File Path"
echo "------------------------------------------"
found_sql=0
find "$TARGET_DIR" -type f \( -name "*.db" \) ! -name "db.db" 2>/dev/null | while read f; do
    size=$(du -sh "$f" 2>/dev/null | cut -f1)
    echo "$size  $f"
    found_sql=1
done
if [ $found_sql -eq 0 ]; then
    echo "None found"
fi
