"""Print the deterministic replay trace as JSON Lines for offline review."""

from backend.incident_investigation.detection import replay_logs


def main() -> None:
    for step in replay_logs():
        print(step.model_dump_json())


if __name__ == "__main__":
    main()
