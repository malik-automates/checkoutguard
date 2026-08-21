import re

from src import checks
from src.auth import login


def main():
    checks.run_workflow(headless=True, no_of_items_added=2)


if __name__ == "__main__":
    main()
