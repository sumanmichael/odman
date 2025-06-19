# Contributing to OneDrive Uploader

## Commit Message Convention

This project follows [Conventional Commits](https://www.conventionalcommits.org/) specification. Please format your commit messages as follows:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation only changes
- **style**: Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc)
- **refactor**: A code change that neither fixes a bug nor adds a feature
- **perf**: A code change that improves performance
- **test**: Adding missing tests or correcting existing tests
- **build**: Changes that affect the build system or external dependencies
- **ci**: Changes to our CI configuration files and scripts
- **chore**: Other changes that don't modify src or test files
- **revert**: Reverts a previous commit

### Examples

```
feat: add file upload progress bar
fix: handle authentication timeout errors
docs: update installation instructions
ci: add automated release workflow
```

### Breaking Changes

For breaking changes, add `!` after the type or include `BREAKING CHANGE:` in the footer:

```
feat!: change API endpoint structure
feat: new authentication method

BREAKING CHANGE: The authentication configuration has changed
```

## Release Process

This project uses automated releases based on conventional commits:

1. **Development**: Make changes with conventional commit messages
2. **Version Bump**: Commitizen automatically determines the next version based on commit types:
   - `fix:` → patch version (0.1.0 → 0.1.1)
   - `feat:` → minor version (0.1.0 → 0.2.0)
   - `feat!:` or `BREAKING CHANGE:` → major version (0.1.0 → 1.0.0)
3. **Changelog**: Automatically updated with commit messages
4. **Release**: GitHub release created with changelog content

## Manual Release (if needed)

If you need to create a release manually:

```bash
# Install commitizen
uv tool install commitizen

# Bump version and update changelog
uv tool run cz bump --changelog

# Push changes and tags
git push --follow-tags origin main
```
