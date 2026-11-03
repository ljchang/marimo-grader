# Course storage

Some notebooks in your course start with a **Sign in with Dartmouth** button and a note about where the data lives. Everything in the notebook works without signing in — it uses the course's public data. Signing in adds two things:

- **The class copy of the data**, including files that are only for your course.
- **Storage that is yours.** Anything you save is there the next time you open *any* notebook — a different chapter, a new molab session, your own laptop — and only you, your instructor and the TAs can see it.

Sign in once per notebook; after that it remembers you.

## In code

```python
from marimo_grader_client import storage

course = storage.course()                   # the class copy, read-only
private = storage.private()                 # yours, read-write

path = course.local_path("data/sub-01/bold.nii.gz")   # an ordinary file path
private.put("week3/results.pkl", results)   # .pkl, .npy, .csv, .json, .nii.gz by extension
private.put("week3/map.nii.gz", brain)      # a nibabel image or nltools BrainData
private.put("week3/map.png", fig)           # a figure: .png, .jpg, .svg, .pdf
results = private.get("week3/results.pkl")
private.ls("week3")
```

`put()` picks the format from the file name. A figure can be a matplotlib figure or axes, a seaborn plot, or a nilearn plot. A table (`.csv`, `.tsv`) can be a pandas or polars DataFrame, an nltools DesignMatrix, or a numpy array; pandas row labels such as region names are kept, the plain 0, 1, 2… are not. To store a file you already wrote, use `private.upload("results.png", "week3/results.png")`.

`local_path()` gives you a real file, so any library that reads files works with it. Once you are signed in, molab's **Files** panel lists the class copy and your own storage under *Remote storage*, where you can browse and download.

Expensive results can be remembered across sessions with a decorator — the second call, even next week in another notebook, is a download instead of a computation:

```python
@storage.cache
def fit_model(subject):
    ...
```

A notebook that already uses marimo's `mo.persistent_cache` can keep that cache in your storage too, by handing it a store:

```python
with mo.persistent_cache("preprocess", store=storage.cache_store()):
    data = data.filter(...).smooth(6)
```

It checks the local disk, then results your instructor computed ahead of time, then your own earlier runs, and only computes when none of them has it. Signed out, it is plain `mo.persistent_cache`. Call it in the `with` line; it finds your sign-in on its own.

## Where it works

- **molab and your own machine:** everything above.
- **The notebook running inside a course web page:** not yet — the notebook falls back to public data and says so.
- **Not enrolled?** Skip the button. The notebook works the same way from the public data.

## What your instructor can see

Your private storage is visible to you, your instructor and the course's TAs — the same people who see your submissions. Other students cannot see it, and the storage never shows anyone's name.
