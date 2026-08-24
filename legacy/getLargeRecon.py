import os
import sys
from omero.gateway import BlitzGateway
from contextlib import redirect_stdout, contextmanager
from lavlab.omero_util import getLargeRecon

@contextmanager
def suppress():
    with open(os.devnull, "w") as null:
        with redirect_stdout(null):
            yield

def get_parent_directory():
    """Get the parent directory of the current script.
    
    Returns:
        str: The parent directory of the current script.
    """
    current_script_path = os.path.abspath(sys.argv[0])  # Get the absolute path of the current script
    parent_directory = os.path.dirname(current_script_path)  # Get the directory of the current script
    return parent_directory

def read_credentials(filename):
    """Read a file containing a username and password.
    
    Args:
        filename (str): The name of the file to read.
    
    Returns:
        tuple: A tuple containing the username and password.
    """
    with open(filename, 'r') as file:
        lines = file.readlines()
        username = lines[0].strip()  # Remove any leading/trailing whitespace
        password = lines[1].strip()  # Remove any leading/trailing whitespace
    
    return username, password
with suppress():
    username, password = read_credentials(get_parent_directory()+os.sep+'omero_user.txt')

    img_id = sys.argv[1]
    downsample_factor=10
    workdir="."
    skip_upload=False
    if len(sys.argv) > 2:
        downsample_factor = int(sys.argv[2])
    if len(sys.argv) > 3:
        workdir = str(sys.argv[3])
    if len(sys.argv) > 4:
        skip_upload = bool(sys.argv[4])

    conn = BlitzGateway(username, password, host='wss://wsi.lavlab.mcw.edu/omero-wss', secure=True)
    print(conn.connect())
    conn.SERVICE_OPTS.setOmeroGroup("-1")
    img = conn.getObject('image', img_id)
    print(img)
    x, y = getLargeRecon(img, downsample_factor, workdir, skip_upload)
    conn.close()
print(y.filename)
