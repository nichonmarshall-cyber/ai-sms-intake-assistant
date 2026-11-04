# AI Memory and AI Scheduling

## Product boundary

These are independent, paid, per-business modules. Enabling AI Intake does not
implicitly enable either module.

- **AI Memory** gives the assistant a small, tenant-scoped context packet made
  from verified customer facts, active work, and a rolling conversation summary.
- **AI Scheduling** reads live calendar availability, applies business rules,
  offers valid slots, and rechecks the selected slot immediately before booking.

The model may explain facts and propose changes. It must not invent or silently
change prices, job statuses, completion estimates, or confirmed appointments.

## Industry-neutral memory model

Memory is not organized around hard-coded verticals such as mechanics or pet
groomers. A business configures reusable record types and fields.

```text
Customer
  -> related records (vehicle, property, equipment, pet, event, claim, etc.)
  -> active work (job, case, order, repair, visit, project, etc.)
  -> appointments
  -> rolling conversation summary
```

Industry templates only prefill this configuration. A plumber may start with
Property and Work Order, while an HVAC company may start with Property, HVAC
Unit, and Service Visit. Both use the same storage and authorization rules.

### Record type configuration

Each tenant-defined record type contains:

- stable key and client-facing label;
- fields with text, long text, number, boolean, date, datetime, choice, phone,
  email, or URL values;
- model access: hidden, read-only, or proposed update;
- update authority: employee only or employee-approved AI proposal;
- retention and sensitivity flags;
- optional status pipeline and customer-facing status wording.

AI-proposed changes are stored separately until approved. Operational facts are
never overwritten directly from a model response.

### Retrieval packet

For each inbound message, tenant and phone number are resolved first. The AI is
given only:

- the matching customer identity;
- explicitly relevant related records;
- active work and next appointment;
- the bounded rolling summary;
- the last few messages.

Raw conversation history remains available for audit, but is not resent on every
turn. This keeps token usage bounded and reduces irrelevant context.

## Scheduling rules

Scheduling is configured per business and optionally overridden per service:

- working days and hours;
- appointment duration;
- buffer before and after;
- minimum notice and maximum booking horizon;
- slot interval and daily capacity;
- approval-required or automatic-booking mode;
- service area/travel rules in a later routing phase.

Availability is computed by expanding each busy Google Calendar interval by the
configured buffers, intersecting the result with working hours, and producing
slots at the configured interval. Before event creation, the exact interval is
queried again to prevent a race with another booking.

After an approval successfully creates the provider event and stores the local
scheduled state, the platform sends a configurable transactional SMS confirming
the approved date and time and explaining that the business may contact the
customer for remaining details. A provider failure never sends this message.

Natural-language preferences remain requests until a precise slot is selected.
The assistant must never say a request is booked before Google returns an event
ID and the local transaction records it.

## Entitlements and rollout

`ai_memory` and `ai_scheduling` are disabled by default. Platform administrators
enable them independently from a business's Module entitlements card.

Recommended delivery order:

1. Entitlements, configuration schema, and audit events.
2. Customer memory records, rolling summaries, and employee approval queue.
3. Context retrieval and deterministic prompt boundaries.
4. Google free/busy availability and conflict-safe booking.
5. Client configuration pages and industry starter templates.
6. CRM/shop-management integrations and travel-time routing.
