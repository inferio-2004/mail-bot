import React, { useState, useEffect } from 'react';
import './App.css';

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:5000';

interface Email {
  id: string;
  snippet: string;
  headers: { [key: string]: string };
  category?: string;
  category_reason?: string;
}

interface SummaryResult {
  llm_text?: string;
  parsed?: {
    summary?: string;
    actions?: Array<{ task: string; deadline?: string; meta?: any }>;
    draft?: { subject: string; body: string };
  };
  error?: string;
}

interface UserInfo {
  email: string;
  name?: string;
  picture?: string;
}

// Component for typewriter effect
const TypewriterMessage: React.FC<{ text: string }> = ({ text }) => {
  const [displayedText, setDisplayedText] = React.useState('');

  React.useEffect(() => {
    if (displayedText.length < text.length) {
      const timer = setTimeout(() => {
        setDisplayedText(text.slice(0, displayedText.length + 1));
      }, 20); // Speed of typewriter effect
      return () => clearTimeout(timer);
    }
  }, [displayedText, text]);

  return <>{displayedText}</>;
};

function App() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [emails, setEmails] = useState<Email[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
  const [summary, setSummary] = useState<SummaryResult | null>(null);
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([]);
  const [question, setQuestion] = useState('');
  const [draftPreview, setDraftPreview] = useState<{ subject?: string; body?: string } | null>(null);
  const [savedDrafts, setSavedDrafts] = useState<Array<any>>([]);
  const [draftSavedMessage, setDraftSavedMessage] = useState<string | null>(null);
  const [messageBody, setMessageBody] = useState<string>('');
  const [classification, setClassification] = useState<{
    category?: string;
    reason?: string;
    tags?: string[];
  } | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>('All');
  const [showSettings, setShowSettings] = useState(false);
  const [customPrompts, setCustomPrompts] = useState<{ [key: string]: string }>({});
  const [rateLimitMessage, setRateLimitMessage] = useState<string | null>(null);

  // Simple localStorage cache to avoid re-summarizing and to store message bodies
  const CACHE_PREFIX = 'mailbot_cache_v1';
  const getCacheKey = (userEmail?: string) => `${CACHE_PREFIX}::${userEmail || user?.email || 'anon'}`;
  const loadCache = (userEmail?: string): any => {
    try {
      const key = getCacheKey(userEmail);
      const raw = localStorage.getItem(key);
      if (!raw) return { summaries: {}, classifications: {}, bodies: {} };
      return JSON.parse(raw);
    } catch (e) {
      return { summaries: {}, classifications: {}, bodies: {} };
    }
  };
  const saveCache = (c: any, userEmail?: string) => {
    try { localStorage.setItem(getCacheKey(userEmail), JSON.stringify(c)); } catch (e) { /* ignore */ }
  };
  const clearCache = (userEmail?: string) => {
    try { localStorage.removeItem(getCacheKey(userEmail)); } catch (e) { /* ignore */ }
  };
  // Try to safely parse JSON returned from the LLM (which may be wrapped in markdown)
  const tryParseJson = (text?: string) => {
    if (!text || typeof text !== 'string') return null;
    try {
      return JSON.parse(text);
    } catch (e) {
      // strip markdown fences and extract first JSON object
      try {
        const m = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
        const candidate = m ? m[1] : text;
        const jmatch = candidate.match(/\{[\s\S]*\}/);
        const jtext = jmatch ? jmatch[0] : candidate;
        return JSON.parse(jtext);
      } catch (e2) {
        return null;
      }
    }
  };

  // Normalize categories returned by LLM into a consistent set used by the UI
  const normalizeCategory = (cat?: string | null) => {
    if (!cat || typeof cat !== 'string') return 'Uncategorized';
    const s = cat.trim().toLowerCase();
    if (!s) return 'Uncategorized';
    if (s.includes('todo') || s === 'to do' || s === 'to-do') return 'To-Do';
    if (s.includes('newsletter')) return 'Newsletter';
    if (s.includes('spam')) return 'Spam';
    if (s.includes('important')) return 'Important';
    // fallback: capitalize words
    return s.split(/\s+/).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  };

  // Note: classification must come from LLM only; no client-side heuristics here.
  const getCachedSummary = (id: string, userEmail?: string) => {
    const c = loadCache(userEmail);
    return c.summaries && c.summaries[id];
  };
  const getCachedClassification = (id: string, userEmail?: string) => {
    const c = loadCache(userEmail);
    return c.classifications && c.classifications[id];
  };
  const getCachedBody = (id: string, userEmail?: string) => {
    const c = loadCache(userEmail);
    return c.bodies && c.bodies[id];
  };
  const setCachedSummaryAndClassification = (id: string, summary: any, classificationObj: any, userEmail?: string) => {
    const c = loadCache(userEmail);
    c.summaries = c.summaries || {};
    c.classifications = c.classifications || {};
    if (summary) c.summaries[id] = summary;
    if (classificationObj) c.classifications[id] = classificationObj;
    saveCache(c, userEmail);
  };
  const setCachedBody = (id: string, body: string, userEmail?: string) => {
    const c = loadCache(userEmail);
    c.bodies = c.bodies || {};
    c.bodies[id] = body;
    saveCache(c, userEmail);
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('connected')) {
      // Fresh OAuth login - fetch user session info
      fetch(`${API_BASE}/user/session`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => {
          if (data.email) {
            setUser(data);
            loadEmails();
            // load user-custom prompts at startup so prompts are available to LLM worker
            loadCustomPrompts();
          }
        })
        .catch(() => {
          setUser({ email: 'Connected' });
          loadEmails();
        });
      window.history.replaceState(null, '', window.location.pathname);
    } else {
      // Check for persistent session via session cookie
      fetch(`${API_BASE}/user/session`, { credentials: 'include' })
        .then(res => {
          if (res.ok) {
            return res.json().then(data => {
              if (data.email) {
                setUser(data);
                loadEmails();
                // ensure custom prompts are loaded on app open
                loadCustomPrompts();
              }
            });
          }
          // 401 or other error means not authenticated; do nothing
        })
        .catch(() => {
          // Network error; not authenticated
        });
    }
  }, []);

  const loadEmails = async () => {
    console.debug('loadEmails: start');
    setLoading(true);
    setRefreshing(true);
    
    // Clear cache on refresh
    clearCache(user?.email);
    try {
      const res = await fetch(`${API_BASE}/email/read?max=30`, { credentials: 'include' });
      const data = await res.json();
      if (data.messages) {
        // initialize emails - on fresh login, don't use cache; always call LLM for categories
        const msgs: Email[] = data.messages.map((m: any) => ({ 
          id: m.id, 
          snippet: m.snippet, 
          headers: m.headers,
          category: 'Classifying...',
          category_reason: ''
        }));
        console.debug('loadEmails: fetched messages count=', msgs.length);
        setEmails(msgs);
        // Batch classify via single LLM call to avoid rate-limit
        try {
          const items = msgs.map(m => ({ id: m.id, subject: m.headers['Subject'] || '' }));
          console.debug('loadEmails: classify-batch will send items=', items.map(i => ({ id: i.id, subject: i.subject?.slice(0,60) })));
          const clsRes = await fetch(`${API_BASE}/llm/classify-batch`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
            body: JSON.stringify({ message_items: items })
          });
          console.debug('loadEmails: classify-batch response status=', clsRes.status);
          if (clsRes.status === 429) {
            // Rate limited — inform user in the summary box
            setRateLimitMessage('Getting too many requests — please try again later.');
            setEmails(msgs.map(m => ({ ...m, category: 'Important', category_reason: 'Classification delayed (rate limit)'})));
          } else {
            const clsData = await clsRes.json();
            console.debug('loadEmails: classify-batch response body=', clsData);
            console.debug('loadEmails: clsData.parsed type=', typeof clsData.parsed, ' value=', clsData.parsed);
            // Expect backend to return a normalized mapping of id -> {category, reason}
            let parsed = (clsData && clsData.parsed) || {};
            console.debug('loadEmails: parsed keys=', Object.keys(parsed));
            console.debug('loadEmails: first msg id=', msgs[0]?.id);
            console.debug('loadEmails: parsed[msgs[0].id]=', msgs[0]?.id ? parsed[msgs[0].id] : 'no-id');
            console.debug('loadEmails: entire parsed object=', JSON.stringify(parsed));
            // build final list with LLM results and cache them
            const enriched = msgs.map(m => {
              const entry = parsed[m.id] || parsed[m.id.toString()] || null;
              console.debug(`loadEmails: for email ${m.id}, entry=${JSON.stringify(entry)}`);
              const rawCat = (entry && entry.category) || '';
              const category = normalizeCategory(rawCat) || 'Important'; // fallback to Important if empty
              const reason = (entry && entry.reason) || 'LLM did not provide a reason';
              // persist classification in cache (per-user) on first load
              try { setCachedSummaryAndClassification(m.id, null, { category, reason }, user?.email); } catch(e){}
              return { ...m, category, category_reason: reason };
            });
            setEmails(enriched);
            setRateLimitMessage(null);
          }
        } catch (e) {
          console.error('Failed to batch classify emails:', e);
          setEmails(msgs.map(m => ({ ...m, category: 'Important', category_reason: 'Classification unavailable' })));
        }
      }
    } catch (err) {
      console.error('Failed to load emails:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Derive a small set of suggested actions from the summary or email when LLM didn't return actions
  const deriveActions = (email: Email | null, summaryResult: SummaryResult | null) => {
    // If the LLM did not return actions, provide a tiny heuristic fallback
    if (!email || !summaryResult) return [];
    const actions: Array<{ task: string; deadline?: string; meta?: any }> = [];
    const txt = (summaryResult.parsed && (summaryResult.parsed.summary || JSON.stringify(summaryResult.parsed))) || summaryResult.llm_text || '';
    if (/follow up|follow-up|please reply|reply needed/i.test(txt)) actions.push({ task: 'Reply to this email' });
    if (/meet|meeting|schedule|call/i.test(txt)) actions.push({ task: 'Schedule a meeting' });
    if (/invoice|payment|due|bill/i.test(txt)) actions.push({ task: 'Review invoice / payment' });
    return actions;
  }

  const loadCustomPrompts = async () => {
    try {
      const res = await fetch(`${API_BASE}/prompts/get-all`, { credentials: 'include' });
      const data = await res.json();
      // Extract just the custom prompts
      const prompts: { [key: string]: string } = {};
      for (const [key, value] of Object.entries(data)) {
        if (typeof value === 'object' && value !== null && 'prompt' in value) {
          prompts[key] = (value as any).prompt;
        }
      }
      setCustomPrompts(prompts);
    } catch (e) {
      console.error('Failed to load prompts:', e);
    }
  };

  const saveCustomPrompt = async (promptType: string, prompt: string) => {
    try {
      const res = await fetch(`${API_BASE}/prompts/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ prompt_type: promptType, prompt })
      });
      const data = await res.json();
      if (data.status === 'saved') {
        // Re-fetch prompts from server to ensure DB is canonical source of truth
        await loadCustomPrompts();
        alert(`${promptType} prompt saved successfully!`);
      } else {
        console.error('save prompt returned unexpected:', data);
        alert('Failed to save prompt');
      }
    } catch (e) {
      console.error('Failed to save prompt:', e);
      alert('Failed to save prompt');
    }
  };

  const resetPrompt = async (promptType: string) => {
    try {
      const res = await fetch(`${API_BASE}/prompts/reset/${promptType}`, {
        method: 'POST',
        credentials: 'include'
      });
      const data = await res.json();
      if (data.status === 'reset') {
        setCustomPrompts(prev => {
          const updated = { ...prev };
          delete updated[promptType];
          return updated;
        });
        alert(`${promptType} prompt reset to default!`);
        await loadCustomPrompts(); // Reload to get default
      }
    } catch (e) {
      console.error('Failed to reset prompt:', e);
    }
  };

  const handleSettingsOpen = () => {
    loadCustomPrompts();
    setShowSettings(true);
  };

  const handleConnectGmail = () => {
    setConnecting(true);
    window.location.href = `${API_BASE}/connect_gmail`;
  };

  const handleSummarize = async (email: Email) => {
    console.debug('handleSummarize: start for', email.id);
    setSelectedEmail(email);
    setSummarizing(true);
    setSummary(null);
    setClassification(null);
    setChatMessages([]);
    setDraftPreview(null);
    setSavedDrafts([]);
    setMessageBody('');
    // If we have a cached summary/classification/body for this email, use what's valid.
    // If any important value is missing (empty summary or missing category), call the backend to fill it.
    let cached: any = null;
    let cachedCls: any = null;
    let cachedBody: any = null;
    try {
      cached = getCachedSummary(email.id, user?.email);
      cachedCls = getCachedClassification(email.id, user?.email);
      cachedBody = getCachedBody(email.id, user?.email);
      const hasSummary = !!(cached && cached.parsed && cached.parsed.summary);
      const hasCategory = !!(cachedCls && cachedCls.category);
      if (hasSummary && hasCategory) {
        // fully cached: ensure spam local action is present when classification indicates spam
        const clsCatCached = (cachedCls && cachedCls.category) || email.category || '';
        const isSpamCached = typeof clsCatCached === 'string' && clsCatCached.toLowerCase().includes('spam');
        if (isSpamCached) {
          console.debug('handleSummarize: cached message detected as spam; enforcing local spam action before early return');
          if (!cached.parsed) cached.parsed = {};
          cached.parsed.actions = [{ task: "Ignore this email — it's spam", deadline: undefined, meta: {} }];
        }
        // fully cached: show and return
        setSummary(cached);
        setClassification(cachedCls || null);
        if (cachedBody) setMessageBody(cachedBody);
        setSummarizing(false);
        setClassifying(false);
        return;
      }
      // otherwise: show any partial cached summary while we fetch missing pieces
      if (cached) {
        setSummary(cached);
      }
      if (cachedCls) {
        setClassification(cachedCls);
      }
      if (cachedBody) setMessageBody(cachedBody);
      // continue to fetch missing parts below
    } catch (ex) {
      // continue to fetch if something goes wrong
    }
    try {
      // Fetch full message body for center column and cache it
      try {
        console.debug('handleSummarize: fetching message body for', email.id);
        const mbRes = await fetch(`${API_BASE}/email/message?message_id=${encodeURIComponent(email.id)}`, { credentials: 'include' });
        console.debug('handleSummarize: message fetch status=', mbRes.status);
        if (mbRes.ok) {
          const d = await mbRes.json();
          console.debug('handleSummarize: message body length=', d && d.body ? (d.body.length || 0) : 0);
          if (d && d.body) {
            setMessageBody(d.body);
            try { setCachedBody(email.id, d.body, user?.email); } catch(e) {}
          } else {
            setMessageBody('Message unavailable');
          }
        } else {
          setMessageBody('Message unavailable');
        }
      } catch (e) {
        console.debug('handleSummarize: message fetch error', e);
        setMessageBody('Message unavailable');
      }
      // Determine whether we need to call summarize/classify based on cached values
      const needSummarize = !(cached && cached.parsed && cached.parsed.summary);
      const needClassify = !(cachedCls && cachedCls.category);
      console.debug('handleSummarize: needSummarize=', needSummarize, 'needClassify=', needClassify, 'cached=', !!cached, 'cachedCls=', !!cachedCls);
      setClassifying(true);
      let sumRes: Response | null = null;
      let clsRes: Response | null = null;
      let actRes: Response | null = null;
      let sumData: any = null;
      let clsData: any = null;
      let actData: any = null;
      try {
        // We'll attempt streaming endpoints for summarize and actions.
        // Classify remains a normal JSON call.
        let classifyPromise: Promise<Response> | null = null;
        if (needClassify) {
          console.debug('handleSummarize: calling classify JSON endpoint');
          classifyPromise = fetch(`${API_BASE}/llm/classify`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) });
        }

        // Determine spam using cached classification first (don't rely on async setState).
        const clsCat = (cachedCls && cachedCls.category) || (classification && classification.category) || email.category || '';
        const isSpam = typeof clsCat === 'string' && clsCat.toLowerCase().includes('spam');
        console.log('handleSummarize: isSpam=', isSpam);

        // Summarize: try streaming endpoint first if needed
        if (needSummarize) {
          try {
            console.debug('handleSummarize: calling summarize-stream');
            const streamRes = await fetch(`${API_BASE}/llm/summarize-stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) });
            if (streamRes.status === 429) {
              const msg = 'Getting too many requests — please try again later.';
              setSummary({ error: msg } as SummaryResult);
              setRateLimitMessage(msg);
              setSummarizing(false);
              setClassifying(false);
              return;
            }
            if (streamRes.ok && streamRes.body) {
              const reader = streamRes.body.getReader();
              const decoder = new TextDecoder();
              let acc = '';
              let done = false;
              while (!done) {
                // eslint-disable-next-line no-await-in-loop
                const { value, done: readDone } = await reader.read();
                done = !!readDone;
                if (value) {
                  acc += decoder.decode(value, { stream: true });
                }
              }
              // store accumulated text as llm_text and attempt to parse JSON
              sumData = { llm_text: acc, parsed: tryParseJson(acc) || undefined } as any;
            } else {
              console.debug('handleSummarize: summarize-stream not available, falling back to JSON');
              const r = await fetch(`${API_BASE}/llm/summarize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) });
              sumRes = r;
            }
          } catch (e) {
            console.error('handleSummarize: summarize-stream error', e);
            // try JSON fallback
            try { sumRes = await fetch(`${API_BASE}/llm/summarize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) }); } catch (ex) { console.error('summarize fallback failed', ex); }
          }
        }

        // Actions: call streaming endpoint if not spam
        if (!isSpam) {
          try {
            console.debug('handleSummarize: calling actions-stream');
            const streamRes = await fetch(`${API_BASE}/llm/actions-stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) });
            if (streamRes.status === 429) {
              // Don't error out completely, just skip actions
              console.debug('handleSummarize: actions-stream rate limited, skipping actions');
            } else if (streamRes.ok && streamRes.body) {
              const reader = streamRes.body.getReader();
              const decoder = new TextDecoder();
              let acc = '';
              let done = false;
              while (!done) {
                // eslint-disable-next-line no-await-in-loop
                const { value, done: readDone } = await reader.read();
                done = !!readDone;
                if (value) acc += decoder.decode(value, { stream: true });
              }
              actData = { llm_text: acc } as any;
              try { actData.parsed = tryParseJson(acc); } catch (e) { actData.parsed = null; }
            } else {
              console.debug('handleSummarize: actions-stream not available, falling back to JSON');
              actRes = await fetch(`${API_BASE}/llm/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) });
            }
          } catch (e) {
            console.error('handleSummarize: actions-stream error', e);
            try { actRes = await fetch(`${API_BASE}/llm/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ message_id: email.id }) }); } catch (ex) { console.error('actions fallback failed', ex); }
          }
        } else {
          console.debug('handleSummarize: skipping actions call for spam message');
        }

        // Wait for classification JSON if requested
        if (classifyPromise) {
          try { clsRes = await classifyPromise; } catch (e) { console.error('classify failed', e); }
        }

        // If we received JSON sumRes (fallback), parse it
        if (!sumData && sumRes) {
          try { sumData = await sumRes.json(); } catch (e) { console.debug('failed parse sumRes json', e); }
        }
        // If we received JSON actRes (fallback), parse it
        if (!actData && actRes) {
          try { actData = await actRes.json(); } catch (e) { console.debug('failed parse actRes json', e); }
        }
      } catch (e) {
        console.error('handleSummarize: LLM fetch error', e);
      }

      console.debug('handleSummarize: summarize status=', sumRes ? sumRes.status : (sumData ? 'streamed' : 'no-call'), ' classify status=', clsRes ? clsRes.status : 'no-call', ' actions status=', actRes ? actRes.status : (actData ? 'streamed' : 'no-call'));
      // Check for rate limit on any endpoint
      if ((sumRes && sumRes.status === 429) || (clsRes && clsRes.status === 429) || (actRes && actRes.status === 429)) {
        const msg = 'Getting too many requests — please try again later.';
        setSummary({ error: msg } as SummaryResult);
        setRateLimitMessage(msg);
        setSummarizing(false);
        setClassifying(false);
        return;
      }
      
      if (sumRes) {
        try { 
          sumData = await sumRes.json();
          // Handle rate limit in response body
          if (sumData && sumData.error === 'rate_limit') {
            const msg = 'Getting too many requests — please try again later.';
            setSummary({ error: msg } as SummaryResult);
            setRateLimitMessage(msg);
            setSummarizing(false);
            setClassifying(false);
            return;
          }
          console.debug('handleSummarize: summarize response=', sumData);
          console.debug('handleSummarize: sumData.parsed=', sumData?.parsed);
          console.debug('handleSummarize: sumData.parsed.summary=', sumData?.parsed?.summary);
        } catch(e) { 
          console.debug('handleSummarize: summarize parse error', e);
        }
      } else if (!sumData) {
        // reuse cached summary when summarize not called and streaming didn't fill it
        sumData = cached || null;
        console.debug('handleSummarize: using cached summary=', sumData);
      }
      if (clsRes) {
        if (clsRes.status === 429) {
          setRateLimitMessage('Getting too many requests — please try again later.');
          clsData = { parsed: null, error: 'rate_limited' };
        } else {
          try { 
            clsData = await clsRes.json();
            console.debug('handleSummarize: classify response=', clsData);
            console.debug('handleSummarize: clsData.parsed=', clsData?.parsed);
            console.debug('handleSummarize: clsData.parsed.category=', clsData?.parsed?.category);
          } catch(e) { 
            console.debug('handleSummarize: classify parse error', e);
          }
        }
      } else {
        // reuse cached classification when classify not called
        clsData = { parsed: cachedCls || null };
        console.debug('handleSummarize: using cached classification=', clsData);
      }
      if (actRes) {
        try { 
          actData = await actRes.json(); 
          console.debug('handleSummarize: actions response=', actData);
          // Handle rate limit in actions response
          if (actData && actData.error === 'rate_limit') {
            actData = null; // Will trigger fallback actions
          }
        } catch(e) { 
          console.debug('handleSummarize: actions parse error', e);
          actData = null;
        }
      } else {
        // If we skipped calling actions because the mail is spam, provide a local recommended action
        const clsCat2 = (cachedCls && cachedCls.category) || (classification && classification.category) || email.category || '';
        const isSpam2 = typeof clsCat2 === 'string' && clsCat2.toLowerCase().includes('spam');
        if (isSpam2) {
          actData = { parsed: { actions: [{ task: "Ignore this email — it's spam", deadline: undefined, meta: {} }] } };
          console.debug('handleSummarize: provided local spam action=', actData);
        }
      }
      // Merge actions into summary parsed if not already there
      if (actData && actData.parsed && actData.parsed.actions) {
        if (!sumData) {
          sumData = { parsed: { actions: actData.parsed.actions } } as any;
          console.debug('handleSummarize: created summary to hold actions for spam/message without summary=', sumData);
        } else {
          if (!sumData.parsed) sumData.parsed = {};
          sumData.parsed.actions = actData.parsed.actions;
          console.debug('handleSummarize: merged actions into summary=', sumData);
        }
      }
      // Normalize actions shape: ensure parsed.actions is an array of action objects
      try {
        if (sumData && sumData.parsed) {
          const a: any = sumData.parsed.actions;
          if (a && typeof a === 'string') {
            // sometimes LLM returns a JSON string or a plain-text list
            try {
              const parsedActions = JSON.parse(a);
              if (Array.isArray(parsedActions)) sumData.parsed.actions = parsedActions;
              else if (typeof parsedActions === 'object') sumData.parsed.actions = [parsedActions];
            } catch (e) {
              // try to split lines into tasks
              const lines = (a as string).split(/\r?\n/).map((l: string) => l.trim()).filter(Boolean);
              if (lines.length > 0) sumData.parsed.actions = lines.map((l: string) => ({ task: l }));
            }
          } else if (a && typeof a === 'object' && !Array.isArray(a)) {
            // single object -> wrap into array
            sumData.parsed.actions = [a];
          }
          // if still missing or empty, leave it — UI will derive fallback actions
        }
      } catch (e) {
        console.debug('handleSummarize: action normalization failed', e);
      }
      // If the message is spam, override any actions with the single local spam action to avoid backend suggestions
      const finalClsCat = (cachedCls && cachedCls.category) || (classification && classification.category) || email.category || '';
      const finalIsSpam = typeof finalClsCat === 'string' && finalClsCat.toLowerCase().includes('spam');
      if (finalIsSpam) {
        if (!sumData) sumData = { parsed: {} } as any;
        if (!sumData.parsed) sumData.parsed = {};
        sumData.parsed.actions = [{ task: "Ignore this email — it's spam", deadline: undefined, meta: {} }];
        console.debug('handleSummarize: enforced local spam action in summary.parsed.actions');
      }
      console.debug('handleSummarize: final sumData=', sumData);
      // Normalize summary parsed output: if parsed.summary missing, try to parse llm_text or fall back to llm_text as summary
      try {
        if (sumData && (!sumData.parsed || !sumData.parsed.summary)) {
          const attempted = tryParseJson(sumData && sumData.llm_text);
          if (attempted && typeof attempted === 'object') {
            // If LLM returned JSON, extract summary from it
            if (attempted.summary && typeof attempted.summary === 'string') {
              // Summary is directly in the parsed object
              sumData.parsed = { ...((sumData.parsed) || {}), ...attempted };
            } else {
              // Look for any string field that looks like a summary
              const summaryField = Object.keys(attempted).find(key => 
                typeof attempted[key] === 'string' && attempted[key].length > 20
              );
              if (summaryField) {
                sumData.parsed = { ...((sumData.parsed) || {}), summary: attempted[summaryField], ...attempted };
              } else {
                // No good summary field found, use fallback
                sumData.parsed = { ...((sumData.parsed) || {}), summary: "Summary processed - check actions below." };
              }
            }
          } else if (sumData && typeof sumData.llm_text === 'string' && sumData.llm_text.trim().length > 0) {
            // take first paragraph or 200 chars as a fallback summary
            const txt = sumData.llm_text.trim();
            const firstPara = txt.split(/\n\n|\r\n\r\n/)[0];
            sumData.parsed = { ...((sumData.parsed) || {}), summary: (firstPara.length <= 300 ? firstPara : firstPara.slice(0, 300) + '...') };
          }
        }
      } catch (e) {
        console.debug('handleSummarize: normalization of summary failed', e);
      }
      console.debug('handleSummarize: sumData keys=', sumData ? Object.keys(sumData) : 'null');
      console.debug('handleSummarize: sumData.parsed=', sumData ? sumData.parsed : 'null');
      console.debug('handleSummarize: sumData.parsed?.summary=', sumData && sumData.parsed ? sumData.parsed.summary : 'no-parsed');
      console.debug('handleSummarize: setting summary state to', sumData);
      setSummary(sumData);
      // extract classification parsed result; if missing, try parsing llm_text or use a heuristic
      let parsedCls = (clsData && clsData.parsed) || null;
      try {
        if (!parsedCls && clsData && clsData.llm_text) {
          const attempt = tryParseJson(clsData.llm_text);
          if (attempt && (attempt.category || attempt.reason)) parsedCls = attempt;
        }
        if (!parsedCls) {
          // No classification returned by LLM; mark as Uncategorized
          parsedCls = { category: 'Uncategorized', reason: 'LLM did not return classification' } as any;
        }
      } catch (e) {
        console.debug('handleSummarize: classification normalization failed', e);
      }
      // normalize the returned category to UI canonical form
      try {
        if (parsedCls && parsedCls.category) parsedCls.category = normalizeCategory(parsedCls.category);
      } catch (e) { /* ignore */ }
      console.debug('handleSummarize: setting classification to', parsedCls);
      setClassification(parsedCls);
      // cache the summary and classification in localStorage and in the inbox list to avoid repeat LLM calls
      try { console.debug('handleSummarize: caching summary/class for', email.id); setCachedSummaryAndClassification(email.id, sumData, parsedCls, user?.email); } catch(e) {}
      try { setEmails(prev => prev.map(e => e.id === email.id ? { ...e, cachedSummary: sumData, cachedClassification: parsedCls } : e)); } catch (ex) {}
      // If the (full) classification differs, update the inbox list so both views match
      try {
        if (parsedCls && parsedCls.category) {
          const normalized = normalizeCategory(parsedCls.category);
          setEmails(prev => prev.map(e => e.id === email.id ? { ...e, category: normalized, category_reason: parsedCls.reason || e.category_reason } : e));
        }
      } catch (e) {
        console.warn('Failed to update email list category', e);
      }
      // Do not automatically seed the chat with the summary — keep chat separate from summary display.
      // (Previously the summary was added into the chat window; user requested it removed.)
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
      // Try streaming endpoint first
      const streamRes = await fetch(`${API_BASE}/llm/ask-stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ message_id: selectedEmail.id, question: q })
      });
      
      if (streamRes.status === 429) {
        setChatMessages((s) => [...s, { role: 'assistant', text: 'Rate limit exceeded. Please try again later.' }]);
        return;
      }
      
      if (streamRes.ok && streamRes.body) {
        // Append an empty assistant message which we'll update as chunks arrive
        setChatMessages((s) => [...s, { role: 'assistant', text: '' }]);
        const reader = streamRes.body.getReader();
        const decoder = new TextDecoder();
        let done = false;
        let accumulated = '';
        while (!done) {
          // eslint-disable-next-line no-await-in-loop
          const { value, done: readDone } = await reader.read();
          done = !!readDone;
          if (value) {
            const chunk = decoder.decode(value, { stream: true });
            accumulated += chunk;
            // Update last assistant message
            setChatMessages(prev => {
              const copy = [...prev];
              // find last assistant message index
              let idx = -1;
              for (let i = copy.length - 1; i >= 0; i--) if (copy[i].role === 'assistant') { idx = i; break; }
              if (idx >= 0) copy[idx] = { ...copy[idx], text: accumulated };
              return copy;
            });
          }
        }
        // streaming complete
        return;
      }
      
      // If streaming not supported, fall back to JSON endpoint
      const res = await fetch(`${API_BASE}/llm/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ message_id: selectedEmail.id, question: q })
      });
      
      // Handle rate limit
      if (res.status === 429) {
        setChatMessages((s) => [...s, { role: 'assistant', text: 'Rate limit exceeded. Please try again later.' }]);
        return;
      }
      
      const data = await res.json();
      
      // Handle rate limit in response body
      if (data && data.error === 'rate_limit') {
        setChatMessages((s) => [...s, { role: 'assistant', text: 'Rate limit exceeded. Please try again later.' }]);
        return;
      }
      
      // prefer parsed answer if available, else llm_text
      let reply = '';
      if (data.parsed) {
        if (data.parsed.draft && data.parsed.draft.subject && data.parsed.draft.body) {
          setDraftPreview({ subject: data.parsed.draft.subject, body: data.parsed.draft.body });
          reply = 'Draft generated. Review and save below.';
        } else if (data.parsed.raw && typeof data.parsed.raw === 'string') {
          reply = data.parsed.raw;
        } else if (data.parsed.summary) {
          reply = data.parsed.summary;
        } else if (data.parsed.answer) {
          reply = data.parsed.answer;
        } else if (data.parsed.actions && Array.isArray(data.parsed.actions)) {
          reply = data.parsed.actions.map((a: any) => a.task || JSON.stringify(a)).join('\n');
        } else {
          try { reply = JSON.stringify(data.parsed, null, 2); } catch (e) { reply = String(data.parsed); }
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
        // show a brief confirmation message and keep saved drafts visible
        setDraftSavedMessage('Draft saved');
        setTimeout(() => setDraftSavedMessage(null), 3000);
      } else {
        // treat response as saved item
        setSavedDrafts((s) => [...s, data]);
        setDraftPreview(null);
        setDraftSavedMessage('Draft saved');
        setTimeout(() => setDraftSavedMessage(null), 3000);
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

  // Prepare actions to display in the UI: coerce LLM output into array, or derive heuristics
  const getActionsToShow = () => {
    try {
      if (!selectedEmail) return { actions: [], message: null };
      const raw: any = summary && summary.parsed;
      if (raw) {
        const actions = raw.actions;
        const message = raw.message;
        if (actions) {
          if (Array.isArray(actions)) return { actions: actions as Array<any>, message };
          if (typeof actions === 'string') {
            try {
              const parsed = JSON.parse(actions);
              if (Array.isArray(parsed)) return { actions: parsed, message };
              if (typeof parsed === 'object') return { actions: [parsed], message };
            } catch (e) {
              const lines = (actions as string).split(/\r?\n/).map((l: string) => l.trim()).filter(Boolean);
              if (lines.length > 0) return { actions: lines.map((l: string) => ({ task: l })), message };
            }
          }
          if (typeof actions === 'object') return { actions: [actions], message };
        }
        // If we have a message but no actions, return it
        if (message && (!actions || (Array.isArray(actions) && actions.length === 0))) {
          return { actions: [], message };
        }
        
        // Check if actions are in the LLM text but not parsed correctly
        if (summary && summary.llm_text && typeof summary.llm_text === 'string') {
          // Look for action-like patterns in the raw LLM text
          const actionKeywords = /(?:action[s]?|todo|task[s]?|should|need to|must|required|follow[- ]?up)/i;
          if (actionKeywords.test(summary.llm_text)) {
            console.debug('Actions keywords found in LLM text but no parsed actions');
          }
        }
      }
      // fallback: derive small heuristic actions from summary or message
      const derived = deriveActions(selectedEmail, summary);
      return { actions: derived || [], message: null };
    } catch (e) {
      console.error('getActionsToShow error:', e);
      return { actions: [], message: null };
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
            <button className="btn" onClick={loadEmails} disabled={loading || refreshing} title="Refresh">
              {refreshing ? (
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div className="spinner"></div>
                  Refreshing...
                </span>
              ) : loading ? 'Loading...' : 'Refresh Emails'}
            </button>
            <button className="btn" onClick={handleSettingsOpen} title="Settings">⚙ Settings</button>
            {user && user.picture && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <img src={user.picture} alt="Profile" style={{ width: 32, height: 32, borderRadius: '50%', border: '2px solid #5b8cff' }} />
                <span style={{ fontSize: 13, color: '#0b1220' }}>{user.name || user.email}</span>
              </div>
            )}
            <button className="btn" onClick={() => {
              // Clear cache on logout
              clearCache(user?.email);
              setUser(null);
              // Clear session on backend
              fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => {});
            }} title="Log out">Log out</button>
          </div>
        </div>

        <div className="columns">
          {/* Email List (left column) */}
          <div className="card inbox-card">
            <h2 className="card-title">Inbox</h2>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 500 }}>Filter by Category:</label>
              <select 
                value={categoryFilter} 
                onChange={(e) => setCategoryFilter(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #ddd', fontSize: 13 }}
              >
                <option value="All">All</option>
                <option value="Important">Important</option>
                <option value="To-Do">To-Do</option>
                <option value="Newsletter">Newsletter</option>
                <option value="Spam">Spam</option>
              </select>
            </div>
            {emails.length === 0 ? (
              <p className="muted">No emails found. Click "Refresh Emails" to load.</p>
            ) : (
              <div className="inbox-list">
                {emails
                  .filter(email => categoryFilter === 'All' || normalizeCategory(email.category) === categoryFilter)
                  .map((email) => (
                  <div
                    key={email.id}
                    onClick={() => handleSummarize(email)}
                    className={"inbox-item" + (selectedEmail?.id === email.id ? ' selected' : '')}
                  >
                    <div className="subject">{email.headers['Subject'] || 'No Subject'}</div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div className="from">From: {email.headers['From']}</div>
                        {email.category && (
                          // show full category name as badge in the inbox list
                          <span
                            className={"category-letter-badge " + (email.category || '').toLowerCase()}
                            title={email.category}
                            aria-label={email.category}
                          >{email.category[0]}</span>
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
                <div style={{ fontWeight:700, fontSize:16, marginBottom: 4 }}>{selectedEmail.headers['From']}</div>
                <div style={{ color:'#666', marginBottom:12, fontSize: 14 }}>{selectedEmail.headers['Subject']}</div>
                <div className="message-body" style={{ border: '1px solid #eee', borderRadius:6, fontSize: 13, lineHeight: 1.5 }}>{messageBody || 'Loading message...'}</div>
              </div>
            ) : (
              <div className="muted">Select an email to view message</div>
            )}
          </div>

          {/* Right column: Summary top, chat + draft below */}
          <div className="right-column">
            <div className="card summary-card">
            <h2 className="card-title">AI Summary</h2>
            {!selectedEmail ? (
              <p className="muted">Select an email to see AI summary</p>
            ) : summarizing ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div className="spinner"></div>
                <span>Analyzing email...</span>
              </div>
            ) : classifying ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div className="spinner"></div>
                <span>Classifying email...</span>
              </div>
            ) : rateLimitMessage ? (
              <p className="error">{rateLimitMessage}</p>
            ) : summary?.error ? (
              <p className="error">Error: {summary.error}</p>
            ) : summary ? (
              <div>
                {/* Show classification (category + reason) under the summary */}
                <div className="category-block">
                  {(() => {
                    const cat = (classification && classification.category) || selectedEmail.category || 'Uncategorized';
                    const reason = (classification && classification.reason) || selectedEmail.category_reason || '';
                    const cls = (cat || '').toString().toLowerCase().replace(/\s+/g, '-');
                    return (
                      <>
                        <span className={`category-badge ${cls}`}>{cat}</span>
                        {reason && <div style={{ marginTop: 8, color: '#666', fontSize: 13 }}>{reason}</div>}
                      </>
                    );
                  })()}
                </div>
                {summary.parsed?.summary ? (
                  <div className="section">
                    <p>{summary.parsed.summary}</p>
                  </div>
                ) : (
                  <div className="section">
                    <p className="muted">Summary processed - check actions below.</p>
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
                {summarizing ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div className="spinner"></div>
                    <span>Analyzing actions...</span>
                  </div>
                ) : (() => {
                  const actionResult = getActionsToShow();
                  const actionsToShow = actionResult.actions;
                  const actionMessage = actionResult.message;
                  return actionsToShow && actionsToShow.length > 0 ? (
                    <ul>
                      {actionsToShow.map((action: any, idx: number) => (
                        <li key={idx}>
                          <strong>{action.task || action}</strong>
                          {action.deadline && <span> - Due: {action.deadline}</span>}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">{actionMessage || "No actions needed."}</p>
                  );
                })()}
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
                    <div key={i} className={`chat-message ${m.role}-message`} style={{ marginBottom: 12, display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                      <div className="chat-bubble" style={{
                        maxWidth: '75%',
                        padding: '10px 14px',
                        borderRadius: m.role === 'user' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                        backgroundColor: m.role === 'user' ? '#5b8cff' : '#f0f0f0',
                        color: m.role === 'user' ? '#fff' : '#0b1220',
                        wordWrap: 'break-word'
                      }}>
                        {m.role === 'assistant' ? <TypewriterMessage text={m.text} /> : m.text}
                      </div>
                    </div>
                  ))
                )}
                  </div>
              <div className="chat-input-row">
                <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyPress={(e) => e.key === 'Enter' && handleSendQuestion()} placeholder="Ask anything about this email" />
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
              {/* Saved Drafts list and transient confirmation */}
              {draftSavedMessage && (
                <div style={{ marginTop: 8, color: '#157f3a', fontWeight: 600 }}>{draftSavedMessage}</div>
              )}
            </div>
            )}
          </div>
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="card" style={{ maxWidth: 600, maxHeight: '90vh', overflowY: 'auto', width: '90%', position: 'relative' }}>
            <button 
              onClick={() => setShowSettings(false)}
              style={{
                position: 'absolute',
                top: 12,
                right: 12,
                background: 'none',
                border: 'none',
                fontSize: 24,
                cursor: 'pointer',
                color: '#666',
                padding: '4px 8px',
                lineHeight: '1'
              }}
              title="Close"
            >
              ✕
            </button>
            <h2 style={{ marginTop: 0, paddingRight: 32 }}>Customize System Prompts</h2>
            <p className="muted">Edit the AI assistant prompts used for various tasks. Leave empty to use defaults.</p>
            
            {['classify', 'summarize', 'actions', 'draft', 'ask'].map((promptType) => (
              <div key={promptType} style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid #eee' }}>
                <h3 style={{ marginBottom: 8, textTransform: 'capitalize' }}>{promptType}</h3>
                <textarea
                  value={customPrompts[promptType] || ''}
                  onChange={(e) => setCustomPrompts(prev => ({ ...prev, [promptType]: e.target.value }))}
                  placeholder={`Edit ${promptType} prompt here...`}
                  style={{
                    width: '100%',
                    height: 120,
                    padding: 8,
                    border: '1px solid #ddd',
                    borderRadius: 6,
                    fontFamily: 'monospace',
                    fontSize: 12,
                    resize: 'vertical'
                  }}
                />
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button className="btn primary" onClick={() => saveCustomPrompt(promptType, customPrompts[promptType] || '')}>Save</button>
                  <button className="btn" onClick={() => resetPrompt(promptType)}>Reset to Default</button>
                </div>
              </div>
            ))}

            <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setShowSettings(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
