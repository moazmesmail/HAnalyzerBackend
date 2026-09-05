from app.platform.logging import configure_logging


def main() -> None:
    configure_logging()
    print("Worker placeholder is ready. Video preparation currently runs from API requests.")


if __name__ == "__main__":
    main()
