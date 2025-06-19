#!/bin/bash

# Manual release script for onedriveuploader
# This script performs a manual release when automated CI/CD is not available

set -e

echo "🚀 Starting manual release process..."

# Check if we're on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "❌ Error: You must be on the main branch to create a release"
    echo "Current branch: $CURRENT_BRANCH"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "❌ Error: You have uncommitted changes. Please commit or stash them first."
    git status --porcelain
    exit 1
fi

# Check if commitizen is installed
if ! uv tool run cz --help &> /dev/null; then
    echo "📦 Installing commitizen..."
    uv tool install commitizen
fi

# Pull latest changes
echo "📥 Pulling latest changes..."
git pull origin main

# Run tests if they exist
if [ -f "tests" ] || [ -d "tests" ]; then
    echo "🧪 Running tests..."
    if command -v pytest &> /dev/null; then
        uv run pytest
    else
        echo "⚠️  No pytest found, skipping tests"
    fi
else
    echo "⚠️  No tests directory found, skipping tests"
fi

# Get current version
CURRENT_VERSION=$(uv tool run cz version --project)
echo "📋 Current version: $CURRENT_VERSION"

# Preview what would be bumped
echo "🔍 Checking what would be bumped..."
NEXT_VERSION=$(uv tool run cz bump --dry-run | grep "bump: version" | cut -d' ' -f3 || echo "no-bump")

if [ "$NEXT_VERSION" = "no-bump" ]; then
    echo "ℹ️  No version bump needed (no feat/fix commits since last release)"
    echo "To create a release anyway, you can:"
    echo "  - Add a 'feat:' or 'fix:' commit"
    echo "  - Use 'cz bump --increment PATCH' to force a patch bump"
    exit 0
fi

echo "📈 Next version would be: $NEXT_VERSION"

# Ask for confirmation
read -p "Do you want to proceed with bumping to version $NEXT_VERSION? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Release cancelled"
    exit 1
fi

# Bump version and update changelog
echo "📝 Bumping version and updating changelog..."
uv tool run cz bump --changelog --yes

# Get the new version
NEW_VERSION=$(uv tool run cz version --project)
echo "✅ Version bumped to: $NEW_VERSION"

# Push changes and tags
echo "📤 Pushing changes and tags..."
git push --follow-tags origin main

echo "🎉 Release $NEW_VERSION completed successfully!"
echo "📋 Next steps:"
echo "  - Check the GitHub repository for the new tag: v$NEW_VERSION"
echo "  - Create a GitHub release manually if automated release workflow is not set up"
echo "  - The CHANGELOG.md has been updated with the latest changes"
