# Release Management Scripts

This directory contains scripts to help with release management.

## Manual Release

If you need to create a release manually (outside of the automated GitHub Actions workflow):

```bash
# Run the manual release script
./scripts/release.sh
```

This will:
1. Check for uncommitted changes
2. Run tests (if available)
3. Bump version using commitizen
4. Update changelog
5. Create git tag
6. Push changes and tags
