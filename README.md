# OneDrive Uploader CLI

A command-line tool to upload files to a specific user's OneDrive using Microsoft Graph API with app-only authentication. Ideal for automated scripts, backups, or any process without user interaction.

## Features

- **App-Only Authentication:** Secure, non-interactive client credentials flow.
- **Resumable Large File Uploads:** Automatically handles large files (>4MB).
- **Simple CLI Interface:** Easy to use command-line arguments.
- **Secure Credential Management:** Reads credentials from environment variables.
- **Cross-Platform:** Works on Linux, macOS, and Windows.

## Prerequisites

1.  **Microsoft Entra ID (Azure AD) App Registration:**

    - Configure the app for client credentials flow.
    - Grant `Files.ReadWrite.All` **Application** permission for Microsoft Graph.
    - Grant admin consent for the permission.
    - Collect the **Application (client) ID**, **Directory (tenant) ID**, **Client Secret Value**, and the **User ID** of the target OneDrive account.

2.  **Local Software:**
    - Python 3.11+
    - Git

## Installation

1.  **Clone the repository:**

    ```sh
    git clone https://github.com/sumanmichael/onedriveuploader.git
    cd onedriveuploader
    ```

2.  **Install with `pip`:**
    ```sh
    pip install .
    ```

## Configuration

Set the following environment variables:

**Linux / macOS** (`~/.bashrc` or `~/.zshrc`):

```sh
export ONEDRIVE_CLIENT_ID="<Your_Application_Client_ID>"
export ONEDRIVE_TENANT_ID="<Your_Directory_Tenant_ID>"
export ONEDRIVE_CLIENT_SECRET="<Your_Client_Secret_Value>"
export ONEDRIVE_USER_ID="<Target_User_ID_or_Email>"
```

**Windows (PowerShell)**:

```powershell
$env:ONEDRIVE_CLIENT_ID="<Your_Application_Client_ID>"
$env:ONEDRIVE_TENANT_ID="<Your_Directory_Tenant_ID>"
$env:ONEDRIVE_CLIENT_SECRET="<Your_Client_Secret_Value>"
$env:ONEDRIVE_USER_ID="<Target_User_ID_or_Email>"
```

Remember to reload your shell or open a new terminal to apply the changes.

## Usage

Run the tool from any directory:

#### **Basic Upload**

To upload a file to the root of the target user's OneDrive:

```sh
onedriveuploader "/path/to/your/local/file.txt"
```

#### **Upload to a Specific Folder**

To upload a file to a specific folder (e.g., Documents/Backups), use the -d or --destination flag. If the folder does not exist, it will be created.

```sh
onedriveuploader "/path/to/server-backup.zip" -d "Server/DailyBackups"
```

The tool will print its progress, including token acquisition, the upload method used (small vs. large), and the final confirmation from the Graph API upon success.

## License

This project is licensed under the MIT License. See the LICENSE file for details.
