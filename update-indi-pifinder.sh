git#!/bin/bash

# Branch to update
BRANCH="indi_mount_control"

echo "=== PiFinder Update Script ==="
cd ~/PiFinder || { echo "PiFinder directory not found."; exit 1; }

echo "[1] Stopping PiFinder service"
sudo systemctl stop pifinder

echo "[2] Updating git remote configuration"
git remote set-url jscheidtmann https://github.com/jscheidtmann/PiFinder.git
git fetch jscheidtmann

echo "[3] Checking out branch"
if git show-ref --verify --quiet refs/heads/$BRANCH; then
    echo " - Local branch exists → checking out"
    git checkout $BRANCH
else
    echo " - Local branch does not exist → creating new branch"
    git checkout -b $BRANCH jscheidtmann/$BRANCH
fi

echo "[4] Pulling latest updates"
git reset --hard HEAD
git pull jscheidtmann $BRANCH

echo "[5] Starting PiFinder service"
sudo systemctl start pifinder

echo "=== PiFinder update completed! ==="
