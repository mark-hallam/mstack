# The method, and why it works this way

The best looking products come from one short, hard-edged week of design, not from endless tweaking. This
skill turns that week into steps any agent can run.

1. **One shared brief with hard rules.** Every builder gets the same brief: what the product is, what every
   option must contain (the same real content and the same example scenario), and rules that make the
   options comparable and shippable (self-contained, accessible, works on a phone, true). When everything
   but the look is held still, the person is comparing looks, not content.
2. **A few whole, working directions in parallel.** Three or four, never more than four. Whole means a real
   page the person can scroll, tap and switch to dark mode, not a picture. Builders from different AI makers
   give a wider spread than one maker asked four times. Each file opens with a paragraph naming its design
   language, its reference points and its trade-off, so the person knows what each one is betting on.
3. **A comparison page with a recommendation.** Four screenshots per option (desktop and phone, light and
   dark) side by side, strengths and watch-outs, and one recommendation: the base to take, what to borrow
   from the others, what it costs, and the one thing the person decides first. The agent recommends. The
   person decides.
4. **The pick.** One option. From here the look is decided.
5. **Variants that differ in structure only.** Up to three per round, built on the locked look: the same
   colours, type, radii, shadows and spacing, copied from the picked file. Layout, navigation, wording and
   density change. A variant that changes the visual style is a different direction, which is a relook.
   Each round ends with two to four numbered questions for the person, each naming the variants that
   answer it differently, so the person answers questions instead of staring at pictures.
6. **Lock, then build.** `lock` copies the picked file's tokens into `brand.json` and checks contrast. The
   build brief copies those tokens, so the finished product looks like the mockup the person chose.
7. **Hand over.** multi-evaluator improves the product that now has a look. Its config can name the
   `brand.json`, and the brand rules then appear in every reviewer's brief as rules a fix must respect
   (not scored).

## The decision rule

Directions only while no look is locked. Variants only after. A relook is the person's call, never the
agent's. This keeps the work cheap (a few mockups, not dozens) and keeps the person's attention on the
decision that matters in each round.

## What it does not do

It does not judge the options. A reviewer can, with multi-evaluator, once a look is chosen. It does not
pick for the person, and it does not publish anything.
