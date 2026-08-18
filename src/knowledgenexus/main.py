from knowledgenexus.presentation.api.app import app

__all__ = ["app", "main"]


def main() -> None:
    import uvicorn

    uvicorn.run(
        "knowledgenexus.presentation.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
