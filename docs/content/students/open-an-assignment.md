# Open an assignment

For students. This page covers getting a notebook open; [Sign in and submit](sign-in-and-submit.md) covers the rest.

Assignments are marimo notebooks. Your course site lists them (on DartBrains, under **Assignments**), and each assignment page shows a preview of the notebook with buttons for the ways you can run it. Your instructor decides which buttons appear.

## Open in MoLab

The usual choice. MoLab is marimo's hosted notebook service: a full Python environment in a browser tab, nothing to install.

1. Click **Open in molab** on the assignment page.
2. Sign in to MoLab if asked. MoLab needs its own account (GitHub or Google); this is separate from your university sign-in, which happens later inside the notebook.
3. Wait for the environment to build. The first open of an assignment installs its packages, which can take a minute; later opens are faster.

MoLab keeps your notebook between sessions under your account. If you want a fresh copy, open the assignment page again.

## Run in the browser

Some assignments run entirely in the page, with no server at all. If the assignment page shows the notebook already running (sliders move, cells execute), you can work there directly. Everything else on this page still applies: Check, sign in, Submit.

Your work in a browser-run page lives only in that tab. Download the notebook if you want to keep a copy.

## Open on the cluster

If your course uses an institutional cluster (at Dartmouth, Discovery through Open OnDemand), the assignment page shows **Open on Discovery**. It launches marimo on the cluster with the notebook in your home directory. Ask your course staff for cluster access first; it is not automatic.

## Work on your own computer

Click **Download** to save the notebook, then, with [uv](https://docs.astral.sh/uv/) installed:

```bash
uv run marimo edit --sandbox glm.py
```

The `--sandbox` flag reads the dependency list inside the notebook and builds an environment for it, so the notebook runs the same way it does in MoLab.

## What you should see

Whichever way you opened it, the notebook has the same shape:

- An introduction and a **Sign in** button near the top.
- One section per question. Each has a place for your work, a **Check** cell that runs instantly, and a **Submit** button.
- Written questions have a text box instead of code.

If a cell says *Complete the code cell above first*, that is the check waiting for your answer, not an error.
