# The demo corpus — invented pages, for recording in public

A live search returns real companies, real headlines and real URLs. None of
those organisations agreed to appear in a demo video, and a recording published
to the world is a different thing from a tool a director runs privately over
their own rushes.

So there is a second way to run the retrieval step: from a bundled set of
invented pages, matched to what the demo footage actually says.

```bash
CURRENTCUT_SEARCH_CORPUS=en .venv/Scripts/python -m app.cli demo
CURRENTCUT_SEARCH_CORPUS=ja .venv/Scripts/python -m app.cli demo
```

Unset — the default, and what the hosted demo runs — calls the Parallel Search
API for real.

## It is not a quieter kind of mock

Everything downstream is the real thing. The corpus goes out through the same
egress gate, so a claim from an off-record segment is refused before it can be
matched. The excerpts are read by the same evidence comparator, which is free to
decide they do not support the claim. Attribution runs the same ranking rule.

Nothing in the corpus declares its own standing. `.gov.example` is classified as
a public authority for exactly the same reason `.gov` and `.go.jp` are — the
suffix, decided from the URL by code — and every other host comes back `web` and
cannot be credited. A recording therefore demonstrates the real rule rather than
a stand-in for it. There is a test that fails if an entry ever tries to name its
own type.

Every host sits under `.example`, which RFC 2606 reserves so it can never
resolve. There is a test for that too: a demo page on a name somebody could
register is a demo page that could one day point at a real site.

## A run using it says so

`provider` is recorded as `demo-corpus` — not `parallel`, not `mock` — in the
agent trace and on every row of the Egress Log, and the CLI prints it before the
run starts. No recording can be presented as a live search by accident, and
anyone reviewing the output can tell which it was without being told.

## What a recording still shows

The corpus is shaped so the honest outcomes survive it. From a real run of the
English shoot:

| on screen | outcome |
|---|---|
| Federal minimum wage $7.25/hour | `Source: www.labourstandards.gov.example` |
| Small businesses employ almost half of workforce | `Source: advocacy.smallbusiness.gov.example` |
| Over 150,000 convenience stores nationwide | checked, but no primary source to credit |
| Nearly all convenience stores sell coffee | nothing backs this — attribute it to the speaker |
| Sells about 200 coffee cups daily | their own figure, nobody publishes it |
| Many shops on this street closed | no named subject, cannot be checked |

That third row is the point. Only a trade body publishes the store count, so the
figure is airable and the attribution is not — and the corpus keeps it that way
rather than inventing an authority for everything. A demo where every number
arrives with a source would be teaching a viewer something false about the
product.

A subject the corpus has nothing to say about returns nothing, exactly as a live
search that finds nothing does. There is no filler page.

## Adding to it

Entries are `{match, url, title, excerpt, published_at}`. `match` is a list of
subject words tested against the gated query — not the transcript, which never
leaves. Write excerpts the way a real page reads, including the dates and the
qualifiers, because the comparator is reading them for exactly that.
