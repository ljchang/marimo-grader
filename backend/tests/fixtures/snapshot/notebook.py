# /// script
# requires-python = ">=3.12"
# dependencies = ["marimo"]
# grader-assignment = "glm"
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""# A synthetic assignment""")
    return


@app.cell
def _():
    betas = [0.5, 1.25, -0.75]
    total = sum(betas)
    total
    return (betas,)


@app.cell
def _(betas, mo):
    mo.ui.table([{"regressor": i, "beta": b} for i, b in enumerate(betas)])
    return


@app.cell
def _(betas):
    print("largest beta:", max(betas))
    return


if __name__ == "__main__":
    app.run()
