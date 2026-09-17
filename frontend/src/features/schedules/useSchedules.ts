"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { schedules, type NewSchedule } from "@/lib/api";
import { keys } from "@/lib/query-client";

export function useSchedules() {
  const client = useApi();
  return useQuery({
    queryKey: keys.schedules(),
    queryFn: () => schedules.list(client),
    // A schedule's next window moves when it fires, which is rare compared
    // with a run's progress, but a list left open overnight should not still
    // be promising a window that has been and gone.
    staleTime: 30_000,
  });
}

export function useSchedule(scheduleId: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.schedule(scheduleId),
    queryFn: () => schedules.get(client, scheduleId),
    staleTime: 30_000,
  });
}

export function useCreateSchedule() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewSchedule) => schedules.create(client, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.schedules() });
    },
  });
}

/**
 * Pause, resume and archive share one hook.
 *
 * Each of them changes the schedule *and* its history, so both queries are
 * invalidated — a detail page showing "active" beside an event saying it was
 * just paused is the kind of disagreement nobody trusts a second time.
 */
export function useScheduleAction(scheduleId: string) {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: "pause" | "resume" | "archive") =>
      schedules[action](client, scheduleId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.schedules() });
      void queryClient.invalidateQueries({ queryKey: keys.schedule(scheduleId) });
    },
  });
}
