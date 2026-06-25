# 1. Clone the repo
git clone https://github.com/ali-az1/UnFollowFind.git
cd UnFollowFind

# 2. (Recommended) create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install Python dependencies
pip install playwright openpyxl beautifulsoup4

# 4. Install the Playwright browser binaries (REQUIRED — easy to forget)
playwright install chromium


python main.py

it may not work as expected for more than 300 followers or following as expected
be careful not to get you instagram account banned
