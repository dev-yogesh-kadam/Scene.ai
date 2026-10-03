# Adding workflows

Save a workflow from ComfyUI (normal **Save**, or **Export (API)**) into `workflows/video/` or
`workflows/image/`, then press **Refresh** on the Create page. Nothing else is needed. The form is
built from the workflow itself.

| In the workflow | In Scene.ai |
|---|---|
| Primitive nodes (String, Int, Float, Boolean) | A field labelled with the node's title |
| A title containing PROMPT, DURATION, SEED, RESOLUTION, or starting with WIDTH / HEIGHT | The matching control: prompt box, 5/10/15 s, random or fixed seed, resolution and orientation |
| Load Image / Load Video / Load Audio nodes and the H3 optional loaders | A reference box. A bypassed loader is an optional slot, switched on only when a file is added. |
| `prompt`, `width`, `height`, `steps`, `cfg`, `seed` typed straight into a node | A field |

To expose a setting, put a titled primitive node in front of it in ComfyUI.

The workflow needs a Save node (Save Video or Save Image). The file type of the result decides
whether it lands in the library as a video or an image.

Loader nodes whose titles contain "first frame", "last frame" or "voice track" get special handling:
a workflow with a prompt, a duration and a first-frame slot can make chained long videos, and the
library's "Continue" and "Use as first frame" buttons fill the first-frame slot.

Subgraphs are supported: a node inside the subgraph instance 105 gets the id `105:<inner id>`.

One limit: a workflow saved by some ComfyUI versions, or written by hand, does not list its node
settings. Scene.ai then asks ComfyUI for the node definitions. It keeps a copy in
`storage/cache/node_definitions.json`, so ComfyUI only has to be running the first time.

## Presets (optional)

A file named `<workflow>.studio.json` next to the workflow adds preset buttons, time estimates,
warnings and tips. `workflows/video/h3_director.studio.json` is the example to copy.

| Key | Purpose |
|---|---|
| `title`, `description` | Shown on the Create page. |
| `options` | Groups of buttons, such as Mode and Quality. |
| `rules` | What each choice changes. `when` picks the choices, `set` writes node inputs as `"<node id>.<input>"`, `add` inserts extra nodes. Rules run in order. |
| `hide` | Node ids whose fields are hidden because the rules set them. |
| `controls` | Extra fields for inputs that have no primitive node. `choices` gives a list to pick from; `"primary": true` keeps the field in view instead of under "More settings". |
| `labels` | Better names for fields and reference boxes, by id (`"114:image"`). |
| `defaults` | Starting values for fields, by id. |
| `optional_refs` | Loader nodes that are left out of the job when no file is given. |
| `required_refs` | Loader nodes that must get a file (their saved file name is not used). |
| `extra_refs` | Reference boxes for inputs that have no loader node. A loader is added when the box is filled. |
| `slots` | Which reference box is the first frame, last frame or voice track, when the titles don't say. |
| `confirm` | Warnings that need a click before generating, with an optional alternative. |
| `estimate` | Minutes per choice and duration, as `[minutes, measured]`. |
| `hints` | The Tips list. |

Without an `estimate` table, the estimate comes from earlier runs with the same settings.
