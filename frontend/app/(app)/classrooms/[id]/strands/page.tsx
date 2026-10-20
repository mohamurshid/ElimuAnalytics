"use client";

/**
 * Add a strand: Grade -> learning area -> sub-strand, from the KICD catalogue.
 *
 * A full page rather than a pop-up, and the grade and learning area live in
 * the address, so the phone's back button steps from an area back to the
 * list of areas - the way a teacher will try to leave it.
 *
 * The class's own grade opens first. The other two are a tap away on
 * purpose: assessing a Grade 5 class on a Grade 4 sub-strand is how a
 * teacher finds where a gap began, and the report is then grounded in the
 * Grade 4 curriculum.
 *
 * Several can be added in one visit. Each add stays on the page and marks
 * the row, rather than sending the teacher back after every tap.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Badge, Button, Card, Loading, Note, PageHeader } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type {
  Catalogue,
  CatalogueArea,
  CatalogueSubStrand,
  Classroom,
  Strand,
} from "@/lib/types";

const GRADES = ["Grade 4", "Grade 5", "Grade 6"];

export default function AddStrandPage() {
  // useSearchParams needs a Suspense boundary above it in the App Router.
  return (
    <Suspense fallback={<Loading what="the curriculum" />}>
      <Picker />
    </Suspense>
  );
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

function Picker() {
  const { id: classId } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();

  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [classes, cat, strands] = await Promise.all([
          api.get<Classroom[]>("/api/classrooms"),
          api.get<Catalogue>("/api/catalogue"),
          api.get<Strand[]>(`/api/classrooms/${classId}/strands`),
        ]);
        if (cancelled) return;
        setClassroom(classes.find((c) => c.class_id === classId) ?? null);
        setCatalogue(cat);
        setAdded(
          new Set(strands.map((s) => s.curriculum_key).filter((k): k is string => !!k)),
        );
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "This class isn’t at your school, or it no longer exists."
            : errorMessage(e, "Could not load the curriculum"),
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [classId]);

  const classGrade = classroom?.grade ?? "";
  const ownGradeListed = GRADES.includes(classGrade);
  const requested = params.get("grade");
  const grade =
    requested && GRADES.includes(requested) ? requested : ownGradeListed ? classGrade : GRADES[0];
  const areaName = params.get("area");
  const gradeData = catalogue?.grades.find((g) => g.grade === grade);
  const area = areaName
    ? gradeData?.learning_areas.find((a) => a.learning_area === areaName)
    : undefined;

  const base = `/classrooms/${classId}/strands`;
  const className = classroom
    ? `${classroom.grade}${classroom.name ? ` ${classroom.name}` : ""}`
    : "the class";

  function pickGrade(next: string) {
    setNotice(null);
    router.replace(`${base}?grade=${encodeURIComponent(next)}`, { scroll: false });
  }

  function openArea(next: CatalogueArea) {
    setNotice(null);
    router.push(
      `${base}?grade=${encodeURIComponent(grade)}&area=${encodeURIComponent(next.learning_area)}`,
    );
  }

  async function add(sub: CatalogueSubStrand) {
    setBusyKey(sub.key);
    setError(null);
    setNotice(null);
    try {
      await api.post<Strand>(`/api/classrooms/${classId}/strands`, { key: sub.key });
      setAdded((prev) => new Set(prev).add(sub.key));
      setNotice(`Added ${sub.number} ${sub.name}.`);
    } catch (e) {
      setError(errorMessage(e, "Could not add the strand"));
    } finally {
      setBusyKey(null);
    }
  }

  const addedIn = (a: CatalogueArea) =>
    a.strands.reduce((n, s) => n + s.sub_strands.filter((x) => added.has(x.key)).length, 0);

  return (
    <>
      <PageHeader
        back={
          area
            ? { href: `${base}?grade=${encodeURIComponent(grade)}`, label: "Learning areas" }
            : { href: `/classrooms/${classId}`, label: className }
        }
        title={area ? area.learning_area : "Add a strand"}
        description={
          area
            ? `${grade} · questions in ${area.language}`
            : `Choose what ${className} is assessed on.`
        }
      />

      <div className="space-y-3">
        <Note tone="error">{error}</Note>
        {notice && (
          <Note tone="ok">
            {notice}{" "}
            <Link href={`/classrooms/${classId}`} className="font-semibold underline underline-offset-2">
              Back to the class
            </Link>
          </Note>
        )}
      </div>

      {!catalogue && !error && <Loading what="the curriculum" />}

      {catalogue && !area && (
        <>
          <div
            role="group"
            aria-label="Grade"
            className="grid grid-cols-3 gap-1 rounded-md border border-line-strong bg-surface p-1"
          >
            {GRADES.map((g) => (
              <button
                key={g}
                type="button"
                aria-pressed={grade === g}
                onClick={() => pickGrade(g)}
                className={`min-h-11 rounded px-2 text-[15px] font-medium
                            ${grade === g ? "bg-sunken text-ink" : "text-ink-muted hover:text-ink"}`}
              >
                {g}
              </button>
            ))}
          </div>
          <p className="mt-2 text-sm text-ink-muted">
            {!classroom || ownGradeListed
              ? grade === classGrade
                ? "This class’s grade."
                : "An earlier or later grade — useful for revisiting work."
              : `${classGrade} isn’t in the catalogue yet; Grades 4–6 come first.`}
          </p>

          <Card className="mt-4">
            <ul className="divide-y divide-line">
              {gradeData?.learning_areas.map((a) => {
                const subs = a.strands.reduce((n, s) => n + s.sub_strands.length, 0);
                const mine = addedIn(a);
                return (
                  <li key={a.learning_area}>
                    {a.available ? (
                      <button
                        type="button"
                        onClick={() => openArea(a)}
                        className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left
                                   hover:bg-sunken"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block text-[15px] font-medium text-ink">
                            {a.learning_area}
                          </span>
                          <span className="block text-sm text-ink-muted">
                            {plural(subs, "sub-strand", "sub-strands")}
                            {mine > 0 && ` · ${mine} added`}
                          </span>
                        </span>
                        <span aria-hidden className="text-ink-subtle">›</span>
                      </button>
                    ) : (
                      <div className="flex min-h-14 items-center gap-3 px-4 py-3">
                        <span className="min-w-0 flex-1">
                          <span className="block text-[15px] font-medium text-ink-subtle">
                            {a.learning_area}
                          </span>
                          <span className="block text-sm text-ink-subtle">
                            Not available yet — this curriculum design hasn’t been loaded.
                          </span>
                        </span>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>
        </>
      )}

      {catalogue && areaName && !area && (
        <Note tone="warn">
          {areaName} isn’t in the {grade} catalogue.{" "}
          <Link href={`${base}?grade=${encodeURIComponent(grade)}`} className="underline">
            See all learning areas
          </Link>
        </Note>
      )}

      {area && (
        <div className="space-y-6">
          {area.strands.map((strand) => (
            <section key={strand.name} aria-label={strand.name}>
              <h2 className="mb-2 text-base font-semibold text-ink">{strand.name}</h2>
              <Card>
                <ul className="divide-y divide-line">
                  {strand.sub_strands.map((sub) => {
                    const isAdded = added.has(sub.key);
                    return (
                      <li key={sub.key} className="flex items-center gap-3 px-4 py-3">
                        <p className="min-w-0 flex-1 text-[15px] text-ink">
                          <span className="text-ink-muted">{sub.number}</span> {sub.name}
                        </p>
                        {isAdded ? (
                          <Badge tone="ok">Added</Badge>
                        ) : (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={busyKey !== null}
                            onClick={() => add(sub)}
                            aria-label={`Add ${sub.number} ${sub.name}`}
                          >
                            {busyKey === sub.key ? "Adding…" : "Add"}
                          </Button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </Card>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
