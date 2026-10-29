"use client";

/**
 * The question sheet for a paper quiz: what the class writes on.
 *
 * Built from the same saved quiz as the marking grid, so question 4 here is
 * column 4 there. It is the learner-facing view, so it is built from what a
 * learner's device would receive - question and options, no key, no mark
 * scheme - and the server never sent more.
 *
 * On screen it shows a Print button and a way back; on paper only the sheet.
 */

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { Button, ButtonLink, Loading, Note } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Classroom, QuizSet } from "@/lib/types";

const LETTERS = ["A", "B", "C", "D", "E", "F"];

export default function PrintQuizPage() {
  const { id: classId, quizId } = useParams<{ id: string; quizId: string }>();
  const [quiz, setQuiz] = useState<QuizSet | null>(null);
  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<QuizSet>(`/api/quizzes/${quizId}`),
      api.get<Classroom[]>("/api/classrooms"),
    ])
      .then(([q, classes]) => {
        if (cancelled) return;
        setQuiz(q);
        setClassroom(classes.find((c) => c.class_id === classId) ?? null);
      })
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load the quiz")));
    return () => {
      cancelled = true;
    };
  }, [quizId, classId]);

  const className = classroom
    ? `${classroom.grade}${classroom.name ? ` ${classroom.name}` : ""}`
    : "";
  const sub = quiz ? (quiz.strand.split(" / ")[1] ?? quiz.strand) : "";

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center gap-2 print:hidden">
        <ButtonLink href={`/classrooms/${classId}/quiz`} variant="ghost" className="-ml-3">
          <Icon name="chevronLeft" className="size-4" /> Back to marking
        </ButtonLink>
        <span className="flex-1" />
        <Button onClick={() => window.print()} disabled={!quiz}>
          <Icon name="paper" className="size-4" /> Print
        </Button>
      </div>

      <Note tone="error">{error}</Note>
      {!quiz && !error && <Loading what="the quiz" />}

      {quiz && (
        <article className="mx-auto max-w-2xl rounded-2xl border border-line bg-surface p-5 text-ink shadow-soft sm:p-8 print:max-w-none print:rounded-none print:border-0 print:bg-transparent print:p-0 print:text-black print:shadow-none">
          <header className="border-b border-line-strong pb-3">
            <h1 className="text-xl font-semibold">{sub}</h1>
            <p className="mt-1 text-sm text-ink-muted print:text-black">
              {className} · {quiz.items.length} questions
            </p>
            <p className="mt-4 text-[15px]">
              Name: ____________________________________ &nbsp; Date: ______________
            </p>
            <p className="mt-2 text-sm text-ink-muted print:text-black">
              Circle the letter of the best answer.
            </p>
          </header>

          <ol className="mt-5 space-y-5">
            {quiz.items.map((item, n) => (
              <li key={item.item_id} className="break-inside-avoid">
                <p className="text-[15px] font-medium">
                  {quiz.numbers[n] ?? n + 1}. {item.question_text}
                </p>
                {item.options.length > 0 ? (
                  <ul className="mt-2 space-y-1 pl-5">
                    {item.options.map((option, k) => (
                      <li key={k} className="text-[15px]">
                        <span className="mr-2 font-semibold">{LETTERS[k]}</span>
                        {option}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 pl-5 text-[15px]">
                    ________________________________________________
                  </p>
                )}
              </li>
            ))}
          </ol>
        </article>
      )}
    </>
  );
}
