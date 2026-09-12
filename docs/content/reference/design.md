# Design document

For anyone who wants the reasoning behind the architecture. The design document records the decisions that shaped marimo-grader: why MoGrader is used as a library rather than forked, why notebooks authenticate through a device-style handshake, why the notebook snapshot is the artifact and the question the unit of grading, the data model, the FERPA controls, and the roadmap.

It is kept as a standalone page in the repository so it can be shared with a reviewer without the rest of the site:

- [docs/design.html on GitHub](https://github.com/ljchang/marimo-grader/blob/main/docs/design.html) (open the raw file in a browser to read it rendered).

The HTTP contract that the notebook widget, the web app, and the publish command all use is on the [API](api.md) page.
