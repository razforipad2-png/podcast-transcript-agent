import argparse
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
from agents.manager import ManagerAgent


def parse_args():
    parser = argparse.ArgumentParser(description="Podcast Transcript Agent")
    parser.add_argument("--url",     help="Direct URL to the podcast episode")
    parser.add_argument("--show",    help="Podcast show name")
    parser.add_argument("--episode", help="Episode title")
    return parser.parse_args()


def build_input(args) -> dict:
    if args.url:
        return {"mode": "url", "url": args.url}
    if args.show and args.episode:
        return {"mode": "search", "show": args.show, "episode": args.episode}
    return None


def main():
    args = parse_args()
    input_data = build_input(args)

    if input_data is None:
        print("Error: provide either --url <url>  or  --show <name> --episode <title>")
        sys.exit(1)

    agent = ManagerAgent()
    result = agent.run(input_data)
    print(result)


if __name__ == "__main__":
    main()
