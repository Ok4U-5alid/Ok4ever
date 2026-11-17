# This is a Python script to explore the explore function
def explore_directory(directory):
    for item in os.listdir(directory):
        print(os.path.join(directory, item))

directory = \
    explore_directory(directory)
    return directory