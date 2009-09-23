import doctest

import pydertron

if __name__ == '__main__':
    doctest.testfile("docs.txt", globs=pydertron.__dict__, verbose=True)
