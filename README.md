# Snapchat Memories Downloader

## Requirements
- Python 3.10

- Pillow
- wget
- piexif



## Installation Instructions
- Clone or Download zip
  -  Extract Files if required
- run `install_requirements.bat`
  -  Alternativly open a terminal from this extracted directory and run `pip install -r reqirements.txt`


## Usage Instructions
- Ensure `snap_data.json` is extracted to the same directory as `main.py`
- Run `main.py`


## Update
If snapchat has delivered the memories as `memories_history.json` and a folder called `memories`. Create a folder called `raw_media` and place all the media in that directory, excluding `memories.html`. Then place `memories_history.json` in the folder next to main.py.

Then run the python files in this order.
1. `rebuild_snap_links.py`
2. `local_server.py` Note: Keep this running 
3. `main.py` 

Once `main.py` has finished running, you may close `local_server.py`

