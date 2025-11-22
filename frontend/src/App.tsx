import React, { useState, useEffect } from 'react';
import './App.css';

const API_BASE = 'http://127.0.0.1:5000';

interface Email {
  id: string;
  snippet: string;
  headers: { [key: string]: string };
  category?: string;
  category_reason?: string;
}

interface SummaryResult {
  llm_text: string;
  parsed: {
    summary?: string;
    actions?: Array<{ task: string; deadline?: string; meta?: any }>;
    draft?: { subject: string; body: string };
  };
  error?: string;
}

function App() {
  const [user, setUser] = useState<{ email: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [emails, setEmails] = useState<Email[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
  const [summary, setSummary] = useState<SummaryResult | null>(null);
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([]);
  const [question, setQuestion] = useState('');
  const [draftPreview, setDraftPreview] = useState<{ subject?: string; body?: string } | null>(null);
  const [savedDrafts, setSavedDrafts] = useState<Array<any>>([]);
  const [messageBody, setMessageBody] = useState<string>('');
  const [classification, setClassification] = useState<{
    category?: string;
    reason?: string;
    tags?: string[];
  } | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [classifying, setClassifying] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('connected')) {
      // Fetch user email from backend session
      fetch(`${API_BASE}/email/read?max=1`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => {
          if (data.messages && data.messages.length > 0) {
            // User is connected, fetch their emails
            setUser({ email: 'Connected' });
            loadEmails();
          }
        })
        .catch(() => {
          setUser({ email: 'Connected' });
        });
      window.history.replaceState(null, '', window.location.pathname);
    }
  }, []);

  const loadEmails = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/email/read?max=10`, { credentials: 'include' });
      const data = await res.json();
      if (data.messages) {
        // initialize emails
        const msgs: Email[] = data.messages.map((m: any) => ({ id: m.id, snippet: m.snippet, headers: m.headers }));
        setEmails(msgs);
        // Fetch classifications for each email in parallel (best-effort)
        try {
          const clsPromises = msgs.map((m) => fetch(`${API_BASE}/llm/classify`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
            body: JSON.stringify({ message_id: m.id })
          }).then(r => r.json()).catch(() => null));
          const clsResults = await Promise.all(clsPromises);
          const enriched = msgs.map((m, idx) => {
            const r = clsResults[idx] || {};
            const parsed = r.parsed || {};
            let category = parsed.category;
            let reason = parsed.reason || '';
            if (!category) {
              // fallback heuristic classifier
              const fb = heuristicClassify(m.snippet || '', m.headers || {});
              category = fb.category;
              reason = fb.reason;
            }
            return { ...m, category, category_reason: reason };
          });
          setEmails(enriched);
        } catch (e) {
          // ignore classification failures
        }
      }
    } catch (err) {
      console.error('Failed to load emails:', err);
    } finally {
      setLoading(false);
    }
  };

  // Simple front-end heuristic classifier when LLM is unavailable or inconclusive
  const heuristicClassify = (snippet: string, headers: { [k: string]: string }) => {
    const s = (snippet || '').toLowerCase();
    const from = (headers['From'] || headers['from'] || '').toLowerCase();
    // to-do signals
    if (/action required|please respond|please review|due|deadline|remind|follow up|task|please do|to do|todo/.test(s)) {
      return { category: 'To-Do', reason: 'Contains action/request language (deadline, review, follow up)'};
    }
    // spam signals
    if (/win|free|congratulations|claim your prize|click here|unsubscribe|noreply@|offers|promo|buy now/.test(s) && !from.includes('amazon') && !from.includes('order')) {
      return { category: 'Spam', reason: 'Contains promotional/spam-like language'};
    }
    // newsletter signals
    if (/unsubscribe|newsletter|update|offers|sale|promo|digest|subscribe/.test(s) || from.includes('news') || from.includes('newsletter')) {
      return { category: 'Newsletter', reason: 'Looks like a newsletter or promotional email'};
    }
    // order/invoice/payment -> important
    if (/order|invoice|payment|receipt|cancelled|shipped|delivery|password|security|account/.test(s) || from.includes('amazon') || from.includes('orders') || from.includes('stripe') ) {
      return { category: 'Important', reason: 'Contains transactional or account-related terms'};
    }
    // default
    return { category: 'Important', reason: 'Defaulted to Important (no clear signals)'};
  }

  // Derive a small set of suggested actions from the summary or email when LLM didn't return actions
  const deriveActions = (email: Email | null, summaryResult: SummaryResult | null) => {
    const text = (summaryResult && summaryResult.parsed && summaryResult.parsed.summary) || (email && email.snippet) || '';
    const s = (text || '').toLowerCase();
    const actions: Array<{ task: string; deadline?: string }> = [];
    if (/payment|invoice|receipt|charge|billing/.test(s)) {
      actions.push({ task: 'Verify payment / invoice details' });
    }
    if (/cancel|cancelled|refund|returned/.test(s)) {
      actions.push({ task: 'Check order cancellation / refund status' });
    }
    if (/delivery|shipped|tracking|delivered/.test(s)) {
      actions.push({ task: 'Track delivery / confirm receipt' });
    }
    if (/reply|respond|please respond|please reply|action required|follow up|follow-up/.test(s)) {
      actions.push({ task: 'Reply to sender / follow up' });
    }
    if (/unsubscribe|newsletter|subscribe|offers|promo|sale/.test(s)) {
      actions.push({ task: 'Unsubscribe or manage subscriptions' });
    }
    if (/password|security|reset|account|verify/.test(s)) {
      actions.push({ task: 'Review account/security instructions' });
    }
    // Fallback: if no actions detected, provide a simple review action
    if (actions.length === 0 && s.trim().length > 0) {
      actions.push({ task: 'Review the email and decide next steps' });
    }
    return actions;
  }

  const handleConnectGmail = () => {
    setConnecting(true);
    window.location.href = `${API_BASE}/connect_gmail`;
  };

  const handleSummarize = async (email: Email) => {
    setSelectedEmail(email);
    setSummarizing(true);
    setSummary(null);
    setClassification(null);
    setChatMessages([]);
    setDraftPreview(null);
    setSavedDrafts([]);
    setMessageBody('');
    try {
      // Fetch full message body for center column
      fetch(`${API_BASE}/email/message?message_id=${encodeURIComponent(email.id)}`, { credentials: 'include' })
        .then(r => r.json())
        .then(d => {
          if (d && d.body) setMessageBody(d.body);
        }).catch(() => {});
      setClassifying(true);
      const [sumRes, clsRes] = await Promise.all([
        fetch(`${API_BASE}/llm/summarize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ message_id: email.id })
        }),
        fetch(`${API_BASE}/llm/classify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ message_id: email.id })
        })
      ]);
      const sumData = await sumRes.json();
      const clsData = await clsRes.json();
      setSummary(sumData);
      // extract classification parsed result
      const parsedCls = (clsData && clsData.parsed) || null;
      setClassification(parsedCls);
      // seed chat with the summary if available
      if (sumData && sumData.parsed && sumData.parsed.summary) {
        setChatMessages([{ role: 'assistant', text: sumData.parsed.summary }]);
      }
    } catch (err) {
      console.error('Failed to summarize:', err);
      setSummary({ error: 'Failed to summarize email' } as SummaryResult);
    } finally {
      setSummarizing(false);
      setClassifying(false);
    }
  };

  const handleSendQuestion = async () => {
    if (!question || !selectedEmail) return;
    const q = question;
    setChatMessages((s) => [...s, { role: 'user', text: q }]);
    setQuestion('');
    try {
      const res = await fetch(`${API_BASE}/llm/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ message_id: selectedEmail.id, question: q })
      });
      const data = await res.json();
      // prefer parsed answer if available, else llm_text
      let reply = '';
      if (data.parsed) {
        // if parsed contains draft, show a message and set draftPreview
        if (data.parsed.draft && data.parsed.draft.subject && data.parsed.draft.body) {
          setDraftPreview({ subject: data.parsed.draft.subject, body: data.parsed.draft.body });
          reply = 'Draft generated. Review and save below.';
        } else {
          reply = JSON.stringify(data.parsed);
        }
      } else if (data.answer) {
        reply = data.answer;
      } else if (data.llm_text) {
        reply = data.llm_text;
      } else {
        reply = 'No answer from LLM';
      }
      setChatMessages((s) => [...s, { role: 'assistant', text: reply }]);
    } catch (e) {
      console.error('ask failed', e);
      setChatMessages((s) => [...s, { role: 'assistant', text: 'Error: failed to contact LLM' }]);
    }
  };

  const handleGenerateDraft = async () => {
    if (!selectedEmail) return;
    try {
      const res = await fetch(`${API_BASE}/llm/draft`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ message_id: selectedEmail.id })
      });
      const data = await res.json();
      const parsed = data.parsed || {};
      if (parsed.subject && parsed.body) {
        setDraftPreview({ subject: parsed.subject, body: parsed.body });
      } else if (parsed.raw && typeof parsed.raw === 'string') {
        // fallback: show raw text
        setDraftPreview({ subject: 'Draft', body: parsed.raw });
      } else {
        setDraftPreview({ subject: 'Draft', body: data.llm_text || 'No draft generated' });
      }
    } catch (e) {
      console.error('generate draft failed', e);
    }
  };

  const handleSaveDraft = async () => {
    if (!selectedEmail || !draftPreview) return;
    try {
      const res = await fetch(`${API_BASE}/email/draft`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ to: selectedEmail.headers['From'] || '', subject: draftPreview.subject, body: draftPreview.body, email: undefined })
      });
      const data = await res.json();
      if (data.status === 'draft_created' || data.status === 'created' || data.id) {
        setSavedDrafts((s) => [...s, data]);
        // clear preview after save
        setDraftPreview(null);
      } else {
        // treat response as saved item
        setSavedDrafts((s) => [...s, data]);
        setDraftPreview(null);
      }
    } catch (e) {
      console.error('save draft failed', e);
    }
  };

  const handleCreateDraft = async (draft: { subject: string; body: string }) => {
    try {
      const res = await fetch(`${API_BASE}/email/draft`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          to: selectedEmail?.headers['From'] || '',
          subject: draft.subject,
          body: draft.body
        })
      });
      const data = await res.json();
      if (data.status === 'draft_created') {
        alert('Draft created successfully!');
      }
    } catch (err) {
      console.error('Failed to create draft:', err);
      alert('Failed to create draft');
    }
  };

  if (!user) {
    return (
      <div className="app-root centered">
        <div className="card small-card">
          <h2>Sign Up for Mail-Bot</h2>
          <p>To use Mail-Bot, connect your Gmail account:</p>
          <button className="btn primary" onClick={handleConnectGmail} disabled={connecting}>
            {connecting ? 'Redirecting...' : 'Login / Sign up'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="app-root">
      <div className="container">
        <div className="topbar">
          <h1 className="brand">Mail-Bot</h1>
          <div className="top-buttons">
            <button className="btn" onClick={loadEmails} disabled={loading} title="Refresh">{loading ? 'Loading...' : 'Refresh Emails'}</button>
            <button className="btn" onClick={() => setUser(null)} title="Log out">Log out</button>
          </div>
        </div>

        <div className="columns">
          {/* Email List (left column) */}
          <div className="card inbox-card">
            <h2 className="card-title">Inbox</h2>
            {emails.length === 0 ? (
              <p className="muted">No emails found. Click "Refresh Emails" to load.</p>
            ) : (
              <div className="inbox-list">
                {emails.map((email) => (
                  <div
                    key={email.id}
                    onClick={() => handleSummarize(email)}
                    className={"inbox-item" + (selectedEmail?.id === email.id ? ' selected' : '')}
                  >
                    <div className="subject">{email.headers['Subject'] || 'No Subject'}</div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div className="from">From: {email.headers['From']}</div>
                        {email.category && (
                          <span className={"category-badge " + (email.category || '').toLowerCase()} style={{ fontSize: 12, padding: '4px 8px' }}>{email.category}</span>
                        )}
                      </div>
                      <div className="snippet">{email.snippet?.substring(0, 140)}...</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Message column (center) */}
          <div className="card message-column">
            {selectedEmail ? (
              <div className="message-inner">
                <div style={{ fontWeight:700, fontSize:16 }}>{selectedEmail.headers['From']}</div>
                <div style={{ color:'#666', marginBottom:8 }}>{selectedEmail.headers['Subject']}</div>
                <div className="message-body" style={{ border: '1px solid #eee', borderRadius:6 }}>{messageBody || 'Loading message...'}</div>
              </div>
            ) : (
              <div className="muted">Select an email to view message</div>
            )}
          </div>

          {/* Right column: Summary top, chat + draft below */}
          <div className="right-column">
            <div className="card summary-card">
            <h2 className="card-title">AI Summary & Actions</h2>
            {!selectedEmail ? (
              <p className="muted">Select an email to see AI summary</p>
            ) : summarizing ? (
              <p>Analyzing email...</p>
            ) : classifying ? (
              <p>Classifying email...</p>
            ) : summary?.error ? (
              <p className="error">Error: {summary.error}</p>
            ) : summary ? (
              <div>
                {classification?.category && (
                  <div className="category-block">
                    <span className={"category-badge " + classification.category.toLowerCase()}>{classification.category}</span>
                    {classification.reason && <div className="muted" style={{ marginTop: 6 }}>{classification.reason}</div>}
                  </div>
                )}
                {summary.parsed?.summary && (
                  <div className="section">
                    <h3>Summary</h3>
                    <p>{summary.parsed.summary}</p>
                  </div>
                )}
                {summary.parsed?.actions && summary.parsed.actions.length > 0 && (
                  <div className="section">
                    <h3>Actions</h3>
                    <ul>
                      {summary.parsed.actions.map((action, idx) => (
                        <li key={idx}>
                          <strong>{action.task}</strong>
                          {action.deadline && <span> - Due: {action.deadline}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {summary.parsed?.draft && (
                  <div className="section">
                    <h3>Suggested Draft</h3>
                    <div className="muted"><strong>Subject:</strong> {summary.parsed.draft.subject}</div>
                    <div className="draft-box">
                      <strong>Body:</strong>
                      <pre style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{summary.parsed.draft.body}</pre>
                    </div>
                    <button className="btn primary" onClick={() => handleCreateDraft(summary.parsed!.draft!)}>Create Draft in Gmail</button>
                  </div>
                )}
                {/* Draft preview moved to chat panel to avoid duplication */}

                {savedDrafts.length > 0 && (
                  <div className="section">
                    <h3>Saved Drafts</h3>
                    <ul>
                      {savedDrafts.map((d, i) => (
                        <li key={i} className="muted">{d.status || JSON.stringify(d)}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="muted">Click "Summarize" on an email to analyze it</p>
            )}
            </div>
            {/* Actions area: sits below the summary card and above the chat */}
            {selectedEmail && (
              <div className="card actions-card" style={{ marginTop: 8 }}>
                <h3 className="card-title">Actions</h3>
                {((summary && summary.parsed && summary.parsed.actions && summary.parsed.actions.length > 0) ? summary.parsed.actions : deriveActions(selectedEmail, summary)).length > 0 ? (
                  <ul>
                    {((summary && summary.parsed && summary.parsed.actions && summary.parsed.actions.length > 0) ? summary.parsed.actions : deriveActions(selectedEmail, summary)).map((action, idx) => (
                      <li key={idx}>
                        <strong>{action.task}</strong>
                        {action.deadline && <span> - Due: {action.deadline}</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No actions available.</p>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  {summary?.parsed?.draft && (
                    <button className="btn" onClick={() => handleCreateDraft(summary.parsed!.draft!)}>Create Draft in Gmail</button>
                  )}
                </div>
              </div>
            )}

            {selectedEmail && (
            <div className="card chat-card" style={{ marginTop: 16 }}>
              <h3 style={{ marginTop:0 }}>Ask anything about this email</h3>
                <div className="chat-messages">
                {chatMessages.length === 0 ? (
                  <div className="muted">No messages yet. Ask anything about this email.</div>
                ) : (
                  chatMessages.map((m, i) => (
                    <div key={i} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 12, color: m.role === 'user' ? '#333' : '#1976d2', fontWeight: 600 }}>{m.role === 'user' ? 'You' : 'Assistant'}</div>
                      <div style={{ marginTop: 4 }}>{m.text}</div>
                    </div>
                  ))
                )}
                  </div>
              <div className="chat-input-row">
                <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask anything about this email" />
                <button className="btn primary" onClick={handleSendQuestion}>Send</button>
                <button className="btn" onClick={handleGenerateDraft}>Draft a reply</button>
              </div>
              {draftPreview && (
                <div className="draft-preview-container">
                  <h4 style={{ marginBottom: 8 }}>Draft Preview</h4>
                  <div className="draft-box">
                    <div style={{ marginBottom: 8 }}><strong>Subject: </strong>{draftPreview.subject}</div>
                    <div><strong>Body:</strong><pre style={{ whiteSpace: 'pre-wrap' }}>{draftPreview.body}</pre></div>
                  </div>
                  <div style={{ marginTop:8 }}>
                    <button className="btn primary" onClick={handleSaveDraft}>Save Draft</button>
                  </div>
                </div>
              )}
            </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
