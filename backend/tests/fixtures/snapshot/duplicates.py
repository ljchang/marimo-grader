import marimo

__generated_with = "0.25.2"
app = marimo.App()


@app.cell
def _():
    runs = []
    return (runs,)


@app.cell
def _(runs):
    runs.append(len(runs) + 1)
    print("run", runs[-1])
    return


@app.cell
def _(runs):
    runs.append(len(runs) + 1)
    print("run", runs[-1])
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
