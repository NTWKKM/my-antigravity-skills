#!/bin/sh
# Native Git pre-commit hook wrapper for repository safety and hygiene

echo "Running pre-commit repository safety check..."

# Run python safety scanner across available system runtimes
if command -v py >/dev/null 2>&1; then
    py -3 scripts/check_repo_safety.py
    STATUS=$?
elif command -v python3 >/dev/null 2>&1; then
    python3 scripts/check_repo_safety.py
    STATUS=$?
else
    python scripts/check_repo_safety.py
    STATUS=$?
fi

if [ $STATUS -ne 0 ]; then
    echo ""
    echo "======================================================================"
    echo "COMMIT ABORTED: Repository safety checks failed."
    echo "Resolve detected path leaks, secrets, or binary blobs before committing."
    echo "======================================================================"
    exit 1
fi

exit 0
