# Sunrise Valley Parent Assistant - Demo Guide

A step-by-step script for showing the Parent Assistant to an audience. It covers what parents see, what school staff see, and how the two connect. A full run takes about 15 minutes.

> **Demo only.** Sunrise Valley School is fictional. Use only the sample data in this folder, and never enter real student or parent details.

## Demo credentials

The app has **no built-in accounts**. Staff unlock the staff portal with an admin key, and staff create parent accounts from inside the portal. You create the parent account live during the demo (Part 4).

| What | Value | Where it's used |
|---|---|---|
| Staff portal admin key | `sunrise-demo-admin-key` | **Staff portal** → Admin key. Set by `scripts/start_demo.ps1` |
| School code | `demo` | Parent **Sign in** (already filled in) |
| Parent username | `priya.demo` | You create it in Part 4 |
| Parent display name | `Priya Sharma` | You create it in Part 4 |
| Parent password | `SunriseDemo#2026` | You create it in Part 4 |

These are public demo values. Never use them on a real or internet-facing server.

## Demo files in this folder

| File | Used in |
|---|---|
| `sunrise-valley-handbook.md` | Part 3, the school handbook the assistant learns from |
| `fee-policy-2026.md` | Part 6, a new policy that goes through approval |

## Before the demo: start the app

1. If the app is already running, stop it: click its terminal window and press **Ctrl + C**.
2. Open PowerShell in the `ai-school-parent-assistant` folder and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
   ```

3. Wait for `Uvicorn running on http://127.0.0.1:8000`, then open **http://127.0.0.1:8000** in your browser.

The script sets the demo admin key and starts the app. Keep that window open during the demo.

**Optional, better answers:** without a local AI model, the assistant replies by quoting the most relevant passage from school documents. To get short, written answers instead, install [Ollama](https://ollama.com), run `ollama pull llama3.2:3b`, and add these two lines to `scripts/start_demo.ps1` before the last line:

```powershell
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = "llama3.2:3b"
```

## Part 1: A parent asks a question (2 min)

**Talking point:** parents get instant answers, but only from information the school has approved.

1. On the home page, point out **"Answers from approved school information"** under *School Assistant*.
2. Click the suggestion **What are the school timings?**
3. Show the answer and its **source** label: every answer says where it came from.
4. Click **How do admissions work?** for a second example.

No sign-in is needed for general questions.

## Part 2: Open the staff portal (1 min)

**Talking point:** staff manage everything the assistant knows, from one place.

1. Click **Staff portal** at the top right.
2. Enter the admin key `sunrise-demo-admin-key` and click **Unlock portal**.
3. Walk through the four counters at the top: **Open questions**, **FAQ entries**, **Documents** and **Drafts to review**.
4. Open **Knowledge base** in the left menu to show the six starter FAQ entries.

## Part 3: Teach the assistant from the handbook (3 min)

**Talking point:** the school uploads its own documents; there's no manual data entry and no outside AI service.

1. In the staff portal, open **Documents** and click **Upload document**.
2. Title: `Parent handbook 2026`. File: `docs/demo/sunrise-valley-handbook.md`.
3. Click **Upload & index**.
4. Click **Parent site** at the top, then ask:
   - `Is the school nut-free?`
   - `When do after-school clubs run?`
   - `What should my child wear to school?`
5. Point out that each answer now comes from **Parent handbook 2026**.

**Optional:** add a quick FAQ instead. In **Knowledge base**, click **Add entry** and enter topic `Sports day`, answer `Sports day is on Friday 12 June 2026. Parents are welcome from 10 AM.`, source `Events calendar 2026`. Then ask the parent assistant `When is sports day?`.

## Part 4: Create a parent account and sign in (2 min)

**Talking point:** parents can't sign themselves up. The school creates every account.

1. In the staff portal, open **Parent accounts**.
2. Enter username `priya.demo`, display name `Priya Sharma`, temporary password `SunriseDemo#2026`, then click **Create account**.
3. Click **Parent site**, then **Sign in**.
4. School code is already `demo`. Enter username `priya.demo` and password `SunriseDemo#2026`, then click **Sign in**.
5. Show that **Policy updates** and **My questions** now work for this parent.

If you see *"Username already exists"*, the account is left over from an earlier demo. Just sign in with it, or create another username.

## Part 5: A question the assistant can't answer (3 min)

**Talking point:** the assistant never guesses. Anything it can't answer from approved information goes to a person.

1. Signed in as Priya, ask: `Can my son bring his pet rabbit to show and tell next week?`
2. The assistant replies that it doesn't have verified information and has **sent the question to school staff**.
3. Open **My questions** to show the question waiting for staff.
4. Switch to the **Staff portal** and open **Parent questions**. The question is under **Needs action**.
5. Click **Assign or reply**, enter `Ms. Rao` in **Assign to**, and click **Save & assign**.
6. In **Verified reply to parent**, write: `Yes, small pets may visit for show and tell on Friday afternoons with the class teacher's agreement.` Click **Resolve**.
7. Switch back to the **Parent site** and open **My questions**. Priya sees the staff reply.

## Part 6: Publish a new policy safely (4 min)

**Talking point:** new policies need approval, and the system catches older information that might contradict them.

1. In the staff portal, open **Policies** and click **Upload draft**.
2. Fill in:
   - Policy key: `fees`
   - Effective date: today's date
   - Title: `Fee policy 2026`
   - File: `docs/demo/fee-policy-2026.md`
3. Click **Upload draft**. The policy appears as a **draft**, and parents can't see it yet.
4. Click **Approve**. Approval is **blocked**, with a message about an *unresolved legacy knowledge overlap*. This is expected.
5. Open **Conflicts**. The new fee policy may overlap with the old **Fees** FAQ entry.
6. Click **Deactivate old entry** and confirm.
7. Go back to **Policies** and click **Approve** again. It now succeeds.
8. Switch to the **Parent site**:
   - Open **Policy updates**. Priya sees **Fee policy 2026**.
   - Ask `Is there a sibling discount on fees?` and `Can I pay school fees in cash?`. Answers now come from the approved policy.

## Wrap-up talking points

- Answers come only from approved school content, with the source shown every time.
- Unanswered questions reach staff, and parents see the reply in **My questions**.
- Policies go through draft → conflict check → approval before parents see them.
- Everything runs locally. No paid AI service or API key is required.

## After the demo

- Stop the app with **Ctrl + C** in its window.
- Everything you added is saved in `school.db` (and the search index in `chroma_data`), so it will still be there next time. In Part 4, sign in with the existing account instead of creating it again.
- To start completely fresh, stop the app and rename `school.db` and the `chroma_data` folder (for example to `school.old.db` and `chroma_data.old`). The app recreates them with the starter data on the next start.

## Troubleshooting

| Problem | Fix |
|---|---|
| Staff portal says *Configure SCHOOL_ADMIN_KEY* or *Invalid admin key* | The app wasn't started with `start_demo.ps1`. Stop it and start it with the script. |
| *Address already in use* / port 8000 busy | Another copy is running. Close its window or press **Ctrl + C** there, then start again. |
| Parent sign-in fails | Check the school code is `demo` and the password matches exactly. After 5 failed tries, sign-in is locked for 5 minutes. |
| Handbook questions go to staff instead of answering | Check the document appears under **Documents**. The first upload can take a minute while the search model loads. |
| Policy approval is blocked | Expected in Part 6. Deactivate the old entry under **Conflicts**, then approve again. |
| Policy doesn't appear in **Policy updates** | The effective date must be today or earlier, and the policy must be **approved**. |
