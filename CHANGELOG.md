## v0.3.0-alpha.0 (2025-08-04)

### Feat

- Implement core OneDrive client and upload/download functionality
- refactoring
- Add download and list functionality; Update README.md

### Fix

- rename package from onedriveuploader to odman
- update installation instructions to reflect correct repository name
- remove version declaration and add VSCode settings for type checking
- issue of passing None for destination_folder
- pass the destination folder from file_info['destination_path']
- set header to 'application/octet-stream'
- using full remote path instead of relative path for local file placement.
- use relative path
- remove hardcode value for max_workers
- ensure path before makers
- edit in stats calc

### Refactor

- Clean up imports and enhance File model with API response handling
- Improve code readability and structure; enhance progress display in upload/download functions

## v0.2.1 (2025-06-20)

### Fix

- correct changelog command syntax in release workflow
- correct changelog command syntax in release workflow
- update changelog command to include tag reference

## v0.2.0 (2025-06-20)

### Feat

- add GitHub Actions workflow for automated release and publishing to PyPI
- enhance file upload functionality with parallel processing and progress tracking

### Fix

- update release workflow for commitizen installation and changelog output format
- update tag format in commitizen configuration to include 'v' prefix

## v0.1.0 (2025-06-20)

### Feat

- update release workflow and documentation for improved clarity and automation
- add automated release workflow and update documentation for versioning and changelog
- enhance progress tracking by adding file size and transfer speed columns
- integrate Rich library for enhanced console output and progress tracking
- enhance upload functionality by adding chunk size and progress options for directory uploads
- enhance authentication by allowing command-line arguments for credentials
- implement remote folder creation and enhance upload functionality
- integrate tqdm for upload progress tracking
- add MIT LICENSE
- add README.md

### Fix

- simplify commitizen command usage in release script
- correct commitizen command check in release script
- correct API URL formatting for folder creation

### Refactor

- reorganize README.md for improved clarity and structure
- update README.md for clarity and conciseness
