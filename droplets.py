#!/usr/bin/env python3

##
# Project: DROPLETS
# ~ Linux, macOS and Windows Web GUI and Widget framework.~
# www.droplets.info
#
# @author Nikola Stamatovic Stamat <stamat@ivartech.com>
##

import argparse
import sys

from droplets.backend import get_droplet


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="droplets",
        description="Launch a droplet widget/app from its directory.",
    )
    parser.add_argument("path", help="path to the widget/app directory")
    parser.add_argument(
        "manifest",
        nargs="?",
        default=None,
        help="optional custom manifest.json (defaults to <path>/manifest.json)",
    )
    args = parser.parse_args(argv)

    get_droplet()(args.path, args.manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
