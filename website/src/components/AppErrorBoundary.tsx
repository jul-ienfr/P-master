import React from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

type AppErrorBoundaryProps = {
  children: React.ReactNode;
};

type AppErrorBoundaryState = {
  error: Error | null;
};

export class AppErrorBoundary extends React.Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = {
    error: null,
  };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("PokerMaster V2 runtime error", error, errorInfo);
  }

  private handleReload = () => {
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          p: 3,
          backgroundColor: "background.default",
        }}
      >
        <Paper
          sx={{
            width: "min(860px, 100%)",
            p: 3,
            borderRadius: 3,
          }}
        >
          <Stack spacing={2}>
            <Typography variant="overline" color="text.secondary">
              PokerMaster V2
            </Typography>
            <Typography variant="h5">Runtime UI error</Typography>
            <Alert severity="error">
              The interface hit an unexpected error and could not finish rendering.
            </Alert>
            <Typography variant="body2" color="text.secondary">
              This guard prevents a blank white screen and exposes the underlying exception so the app remains debuggable.
            </Typography>
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 2,
                borderRadius: 2,
                overflowX: "auto",
                backgroundColor: "rgba(15, 23, 42, 0.08)",
                color: "text.primary",
                fontSize: 13,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {this.state.error.stack || this.state.error.message}
            </Box>
            <Box>
              <Button variant="contained" onClick={this.handleReload}>
                Reload PokerMaster
              </Button>
            </Box>
          </Stack>
        </Paper>
      </Box>
    );
  }
}
