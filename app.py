"""Point d'entrée de développement de ClasseXP."""

from classexp import create_app


app = create_app()


if __name__ == "__main__":
    app.run()
