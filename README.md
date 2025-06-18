# **OneDrive Uploader CLI**

A command-line tool to upload files directly to a specific user's OneDrive account using Microsoft Graph API with app-only authentication. This is ideal for automated server-side scripts, backups, or any process where user interaction is not possible.

The tool securely uses environment variables for credentials and automatically handles both small (<4MB) and large files by using the appropriate upload method (single request vs. resumable upload session).

## **Features**

- **App-Only Authentication:** Uses a secure, non-interactive client credentials flow. No user login required.

- **Resumable Large File Uploads:** Automatically uses Microsoft Graph's resumable upload session for files larger than 4MB, ensuring reliability.

- **Simple CLI Interface:** Easy-to-use command-line arguments for specifying the source file and optional destination folder.

- **Secure Credential Management:** Reads all required credentials from environment variables to avoid hardcoding secrets in your code.

- **Cross-Platform:** Works on any operating system where Python is supported (Linux, macOS, Windows).

## **1. Prerequisites**

Before you begin, ensure you have the following set up:

### **a) Microsoft Entra ID (Azure AD) App Registration**

You must have an application registered in your Microsoft Entra ID tenant with the following configuration:

- **Authentication:** The app must be configured for the client credentials flow (app-only).

- **API Permissions:** The app must be granted the following **Application** permission for Microsoft Graph:

* Files.ReadWrite.All

- **Admin Consent:** An administrator must grant admin consent for the Files.ReadWrite.All permission in the Azure portal.

You will need to collect the following credentials from your app registration:

- **Application (client) ID**

- **Directory (tenant) ID**

- **Client Secret Value**

- **User ID** (The User Principal Name, e.g., user\@yourdomain.com, or the Object ID of the user whose OneDrive will be the upload target).

### **b) Local Software**

- **Python** (version 3.11 or newer)

- **Git**

- **pipx** (recommended for installing Python CLI tools)

* If you don't have pipx, install it with:\
  python3 -m pip install --user pipx\
  python3 -m pipx ensurepath

* _You may need to restart your terminal after running ensurepath._

## **2. Installation**

1. Clone the Repository:\
   Open your terminal and clone this project from GitHub.\
   git clone https\://github.com/sumanmichael/onedriveuploader.git\
   cd onedriveuploader

2. Install with pipx:\
   Use pipx to install the tool from the local project directory. This will build the package and add the onedriveuploader command to your system's PATH.\
   pipx install .\
   \
   You should see a confirmation message that the onedriveuploader app was installed successfully.

## **3. Configuration**

The tool requires four environment variables to be set for authentication.

Linux / macOS

Add the following lines to your shell profile file (e.g., \~/.bashrc, \~/.zshrc).

export ONEDRIVE_CLIENT_ID="\<Your_Application_Client_ID>"\
export ONEDRIVE_TENANT_ID="\<Your_Directory_Tenant_ID>"\
export ONEDRIVE_CLIENT_SECRET="\<Your_Client_Secret_Value>"\
export ONEDRIVE_USER_ID="\<Target_User_ID_or_Email>"

_Remember to reload your shell (source \~/.bashrc) or open a new terminal window to apply the changes._

Windows (PowerShell)

You can set the variables for the current session:

$env:ONEDRIVE\_CLIENT\_ID="\<Your\_Application\_Client\_ID>"\
$env:ONEDRIVE_TENANT_ID="\<Your_Directory_Tenant_ID>"\
$env:ONEDRIVE\_CLIENT\_SECRET="\<Your\_Client\_Secret\_Value>"\
$env:ONEDRIVE_USER_ID="\<Target_User_ID_or_Email>"

_To set them permanently, search for "Edit the system environment variables" in the Start Menu._

## **4. Usage**

Once installed and configured, you can run the tool from any directory.

#### **Basic Upload**

To upload a file to the root of the target user's OneDrive:

onedriveuploader "/path/to/your/local/file.txt"

#### **Upload to a Specific Folder**

To upload a file to a specific folder (e.g., Documents/Backups), use the -d or --destination flag. If the folder does not exist, it will be created.

onedriveuploader "/path/to/server-backup.zip" -d "Server/DailyBackups"

The tool will print its progress, including token acquisition, the upload method used (small vs. large), and the final confirmation from the Graph API upon success.

## **License**

This project is licensed under the MIT License. See the LICENSE file for details.
