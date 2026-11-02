# 90 to 120 second demo script

Record at 1440 x 900. Start with an empty `data/` folder and both servers running.

1. **0:00** Documents page. "Four fictional samples, three with an injected extraction fault."
   Import **Preset total error**.
2. **0:10** Point at the "Preset extraction error (demo fault)" label. "The PDF says 50,000.00;
   the candidate says 500,000.00." Show the failing total rule and its difference.
3. **0:25** Click *Total amount due*: the highlighter box lands on the printed value. Switch
   to 150% and back; the box stays on the number.
4. **0:40** Type `50,000`. Note "unsaved changes", Confirm disabled. Enter a reason, Save.
   Rules pass. Open History: `500000.00 to 50000.00`, reason, actor. The extracted value is
   still shown beside the correction.
5. **0:55** "Rules pass, but nobody has looked." Tick the six checks; the counter climbs.
   Confirm review.
6. **1:10** Export JSON. Open the file: amounts are strings, each field has source text and
   position, rules, confirmation, history.
7. **1:25** Edit a field on the confirmed record. Save. Confirmation withdraws, checks clear.
   (Or: open the same record in a second window and show the stale save being refused with the
   draft kept.)
8. **1:40** Counter-example: open **Missing source value**. The due date has no source
   location; its check box is disabled; Confirm stays disabled.

Do not describe the faults as model errors, and do not quote accuracy or time-saved figures.
