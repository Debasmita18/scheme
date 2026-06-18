import React, { useEffect, useRef, useState } from 'react';
import {
  Button, Dialog, DialogContent, LinearProgress, Box, Typography,
  Snackbar, Alert, CircularProgress,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { tokens } from '../../theme.js';

const DEFAULT_STEPS = [
  'Collating muster rolls & job cards…',
  'Running satellite change detection…',
  'Analysing payment network graph…',
  'Scoring statistical anomalies…',
  'Drafting evidence dossier with AI…',
];

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function downloadFile(filename, content, mime = 'text/html') {
  triggerDownload(new Blob([content], { type: mime }), filename);
}

function downloadBase64(filename, b64, mime = 'application/pdf') {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  triggerDownload(new Blob([bytes], { type: mime }), filename);
}

/**
 * Button that runs an async `task` (e.g. an AI generation call) behind a
 * progress dialog, then DOWNLOADS the returned file and shows a snackbar.
 * `task` must resolve to { filename, html|content, mime? }.
 * Without a task it falls back to a simulated run (no download).
 */
export default function GenerateButton({
  label = 'Generate', icon, fullWidth = false, variant = 'outlined', sx,
  title = 'Generating report', steps = DEFAULT_STEPS, task,
  doneMessage = 'Document generated & downloaded',
}) {
  const [open, setOpen] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stepIdx, setStepIdx] = useState(0);
  const [snack, setSnack] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef(null);
  const mounted = useRef(true);

  useEffect(() => {
    // Set true on every (re)mount — StrictMode mounts→unmounts→remounts in dev,
    // and the cleanup below would otherwise leave this permanently false.
    mounted.current = true;
    return () => { mounted.current = false; clearInterval(timer.current); };
  }, []);

  const animate = (done) => {
    clearInterval(timer.current);
    timer.current = setInterval(() => {
      setProgress((p) => {
        const cap = done.current ? 100 : 92;
        const np = Math.min(cap, p + (done.current ? 6 : 1.4));
        setStepIdx(Math.min(steps.length - 1, Math.floor((np / 100) * steps.length)));
        if (np >= 100) clearInterval(timer.current);
        return np;
      });
    }, 45);
  };

  const start = async () => {
    if (open) return;
    setError('');
    setOpen(true);
    setProgress(0);
    setStepIdx(0);
    const done = { current: false };
    animate(done);
    try {
      const result = task ? await task() : await new Promise((r) => setTimeout(r, 2200));
      done.current = true;
      // let the bar finish to 100%
      await new Promise((r) => setTimeout(r, 450));
      if (result && result.pdf_base64) {
        downloadBase64(result.filename || 'report.pdf', result.pdf_base64, 'application/pdf');
      } else if (result && (result.html || result.content)) {
        downloadFile(result.filename || 'report.html', result.html || result.content, result.mime || 'text/html');
      }
      if (mounted.current) setSnack(true);
    } catch (e) {
      if (mounted.current) setError(e?.message || 'Generation failed');
    } finally {
      // Always stop the spinner and close the dialog, no matter what.
      done.current = true;
      clearInterval(timer.current);
      if (mounted.current) setOpen(false);
    }
  };

  return (
    <>
      <Button
        variant={variant}
        fullWidth={fullWidth}
        startIcon={open ? <CircularProgress size={16} color="inherit" /> : icon}
        onClick={start}
        disabled={open}
        sx={sx}
      >
        {open ? 'Generating…' : label}
      </Button>

      <Dialog open={open} PaperProps={{ sx: { borderRadius: 3, minWidth: { xs: 280, sm: 400 } } }}>
        <DialogContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <CircularProgress size={22} thickness={5} />
            <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 16 }}>{title}</Typography>
          </Box>
          <LinearProgress
            variant="determinate" value={progress}
            sx={{ height: 8, borderRadius: 4, mb: 1.2, '& .MuiLinearProgress-bar': { background: `linear-gradient(90deg, ${tokens.saffronDeep}, ${tokens.saffron})` } }}
          />
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography sx={{ fontSize: 12.5, color: tokens.textDim }}>{steps[stepIdx]}</Typography>
            <Typography sx={{ fontSize: 12.5, fontWeight: 700, color: tokens.saffron }}>{Math.round(progress)}%</Typography>
          </Box>
          <Typography sx={{ fontSize: 11, color: tokens.textDim, mt: 1.5 }}>
            Powered by on-portal forensics + Groq AI · the document will download automatically.
          </Typography>
        </DialogContent>
      </Dialog>

      <Snackbar open={snack} autoHideDuration={4000} onClose={() => setSnack(false)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
        <Alert icon={<CheckCircleIcon fontSize="inherit" />} severity="success" variant="filled" onClose={() => setSnack(false)}>
          {doneMessage} — check your downloads.
        </Alert>
      </Snackbar>

      <Snackbar open={!!error} autoHideDuration={6000} onClose={() => setError('')} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
        <Alert severity="error" variant="filled" onClose={() => setError('')}>{error}</Alert>
      </Snackbar>
    </>
  );
}
