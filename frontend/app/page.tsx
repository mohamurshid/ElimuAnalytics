"use client";

/**
 * The landing page (25 October): what Elimu Analytics is, why it measures
 * with Item Response Theory rather than percentages, and how a teacher uses
 * it - with the way in at the top and the bottom.
 *
 * It replaced a page that only redirected. A signed-in teacher is no longer
 * sent away from "/" but offered "Open Elimu", so the page doubles as the
 * explanation a head teacher can show a colleague.
 *
 * There is no open sign-up: a head teacher adds each teacher and gives them
 * a one-time setup code. So the main call to action is "Set up your
 * account", and the page says where the code comes from.
 *
 * The explainers run the same 2-PL model and rules as the server
 * (lib/irt.ts) on invented learners; nothing here shows real data.
 */

import Link from "next/link";

import { CurveExplorer } from "@/components/landing/CurveExplorer";
import { HeroHeatmap } from "@/components/landing/HeroHeatmap";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { SameScore } from "@/components/landing/SameScore";
import { Logo } from "@/components/Logo";
import { SiteHeader } from "@/components/SiteHeader";
import { useAuth } from "@/lib/auth";
import { HOME } from "@/lib/routes";

const PRIMARY =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-action px-6 text-[15px] font-semibold text-action-ink shadow-soft transition-all hover:bg-action-hover hover:shadow-lift active:scale-[0.98]";
const SECONDARY =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-full border border-line-strong bg-surface px-6 text-[15px] font-semibold text-ink transition-colors hover:bg-sunken";

const ADVANTAGES = [
  {
    title: "Fair across different quizzes",
    body: "Learners may answer different questions — a new quiz, a question added later. IRT places them all on one scale, because it knows how hard each question is.",
  },
  {
    title: "Blank is not wrong",
    body: "A question a learner did not attempt is left out of their estimate. Counting it as wrong would pull every estimate down.",
  },
  {
    title: "Knows when it doesn't know",
    body: "No level below five answers on a strand, and a level is marked provisional until ten. A child is never flagged on a guess.",
  },
  {
    title: "Measures the questions too",
    body: "Each question gets a difficulty and a discrimination from real answers. A question that does not separate stronger from weaker learners is flagged.",
  },
  {
    title: "Speaks KICD's language",
    body: "Abilities are reported as Below, Approaches, Meets or Exceeds expectation — the four levels teachers already use.",
  },
  {
    title: "Support, not just a score",
    body: "Learners who are low twice in a row rise to the top of the support list, with a report that quotes the curriculum on what to teach next.",
  },
];

export default function LandingPage() {
  const { profile, resolved } = useAuth();
  const signedIn = resolved && profile !== null;

  return (
    <div className="min-h-screen bg-canvas">
      <SiteHeader />

      <main>
        {/* --- hero -------------------------------------------------------- */}
        <section className="relative overflow-hidden">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 [background-image:radial-gradient(var(--border)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]"
          />
          <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pb-16 pt-12 sm:px-6 md:pt-20 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:pb-24">
            <div className="animate-[fade-up_500ms_ease-out]">
              <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-muted">
                <span className="size-1.5 rounded-full bg-ok" />
                Kenya CBE · Grades 4–6 · English and Kiswahili
              </p>
              <h1 className="mt-5 text-[2.5rem] font-semibold leading-[1.08] tracking-tight text-ink sm:text-5xl lg:text-[3.5rem]">
                Know who needs support, and what to teach them next.
              </h1>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-muted">
                Elimu Analytics turns short quizzes into each learner&apos;s level on every
                strand — measured with Item Response Theory, the method behind large-scale
                assessments such as PISA — and suggests next steps grounded in the KICD
                curriculum.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                {signedIn ? (
                  <Link href={HOME} className={PRIMARY}>
                    Open Elimu Analytics
                  </Link>
                ) : (
                  <>
                    <Link href="/setup" className={PRIMARY}>
                      Set up your account
                    </Link>
                    <Link href="/login" className={SECONDARY}>
                      Sign in
                    </Link>
                  </>
                )}
              </div>
              {!signedIn && (
                <p className="mt-4 text-sm text-ink-subtle">
                  Your head teacher adds you to the staff list and gives you a setup code.
                </p>
              )}
            </div>
            <div className="animate-[fade-up_700ms_ease-out] lg:pl-6">
              <HeroHeatmap />
            </div>
          </div>
        </section>

        {/* --- facts -------------------------------------------------------- */}
        <section aria-label="At a glance" className="border-y border-line bg-surface">
          <dl className="mx-auto grid max-w-6xl grid-cols-2 gap-px bg-line md:grid-cols-4">
            {[
              ["427", "KICD sub-strands to assess"],
              ["4", "KICD levels, from Below to Exceeds"],
              ["2", "languages for every report"],
              ["100%", "of AI questions approved by a teacher before use"],
            ].map(([n, label]) => (
              <div key={label} className="bg-surface px-4 py-6 sm:px-6">
                <dt className="sr-only">{label}</dt>
                <dd className="text-3xl font-semibold tracking-tight text-ink">{n}</dd>
                <dd className="mt-1 text-sm text-ink-muted">{label}</dd>
              </div>
            ))}
          </dl>
        </section>

        {/* --- why not percentages --------------------------------------- */}
        <section id="why" className="scroll-mt-20">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <SectionHead
              kicker="Why IRT"
              title="Percentages can mislead."
              lead="A percentage treats every question as equal. Item Response Theory knows that some questions are harder than others, so it can tell how able a learner is even when learners answer different questions. Tap any answer to change it."
            />
            <div className="mt-10">
              <SameScore />
            </div>
          </div>
        </section>

        {/* --- the curve -------------------------------------------------- */}
        <section id="curve" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <SectionHead
              kicker="The model"
              title="How one question behaves."
              lead="Elimu uses the two-parameter logistic model. Each question has a difficulty and a discrimination; each learner has an ability. Together they give the chance of a correct answer — this curve. From many answers, Elimu works backwards to every learner's ability."
            />
            <div className="mt-10">
              <CurveExplorer />
            </div>
          </div>
        </section>

        {/* --- advantages -------------------------------------------------- */}
        <section aria-labelledby="adv-heading">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <SectionHead kicker="What it gives you" title="Built for a real classroom." id="adv-heading" />
            <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {ADVANTAGES.map((a, i) => (
                <li
                  key={a.title}
                  className="group rounded-2xl border border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lift"
                >
                  <span className="flex size-9 items-center justify-center rounded-xl bg-sunken text-sm font-semibold text-ink transition-colors group-hover:bg-action group-hover:text-action-ink">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3 className="mt-4 text-[17px] font-semibold text-ink">{a.title}</h3>
                  <p className="mt-1.5 text-[15px] leading-relaxed text-ink-muted">{a.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* --- how it works ------------------------------------------------ */}
        <section id="how" className="scroll-mt-20 border-t border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <SectionHead
              kicker="How it works"
              title="From a strand to a support plan, in five steps."
              lead="The teacher stays in charge at every step: nothing written by AI is used until a teacher approves it, and a level is evidence for your judgement, not a replacement for it."
            />
            <div className="mt-10">
              <HowItWorks />
            </div>
          </div>
        </section>

        {/* --- call to action --------------------------------------------- */}
        <section className="px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-4xl rounded-3xl bg-action px-6 py-12 text-center text-action-ink sm:px-12">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Ready when your class is.</h2>
            <p className="mx-auto mt-3 max-w-xl text-[17px] leading-relaxed opacity-80">
              Ask your head teacher to add you, then set up your account with the code they
              give you. Already set up? Sign in with your password or with Google.
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              {signedIn ? (
                <Link href={HOME} className="inline-flex min-h-12 items-center justify-center rounded-full bg-canvas px-6 text-[15px] font-semibold text-ink hover:opacity-90">
                  Open Elimu Analytics
                </Link>
              ) : (
                <>
                  <Link href="/setup" className="inline-flex min-h-12 items-center justify-center rounded-full bg-canvas px-6 text-[15px] font-semibold text-ink transition-opacity hover:opacity-90">
                    Set up your account
                  </Link>
                  <Link href="/login" className="inline-flex min-h-12 items-center justify-center rounded-full border border-current/30 px-6 text-[15px] font-semibold transition-colors hover:bg-white/10">
                    Sign in
                  </Link>
                </>
              )}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-sm text-ink-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <Logo />
          <p>
            Learning-gap detection for Kenya&apos;s Competency-Based Education. Final-year project,
            Strathmore University.
          </p>
        </div>
      </footer>
    </div>
  );
}

function SectionHead({
  kicker,
  title,
  lead,
  id,
}: {
  kicker: string;
  title: string;
  lead?: string;
  id?: string;
}) {
  return (
    <div className="max-w-2xl">
      <p className="text-sm font-semibold uppercase tracking-wider text-ink-subtle">{kicker}</p>
      <h2 id={id} className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        {title}
      </h2>
      {lead && <p className="mt-4 text-[17px] leading-relaxed text-ink-muted">{lead}</p>}
    </div>
  );
}
