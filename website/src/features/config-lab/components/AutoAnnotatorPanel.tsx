import { useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import Alert from "@mui/material/Alert";
import Paper from "@mui/material/Paper";
import IconButton from "@mui/material/IconButton";
import {
  AutoAnnotatorProviderConfig,
  createDefaultAutoAnnotatorConfig,
  loadAutoAnnotatorConfig,
  persistAutoAnnotatorConfig,
} from "../../../lib/autoAnnotator";

// Icônes textuelles simples (compatibles sans installer de lib supplémentaire)
const DeleteIcon = () => <span style={{ fontSize: "1.2rem" }}>🗑️</span>;
const AddIcon = () => <span style={{ fontSize: "1.2rem" }}>➕</span>;
const UpIcon = () => <span style={{ fontSize: "1.2rem" }}>⬆️</span>;
const DownIcon = () => <span style={{ fontSize: "1.2rem" }}>⬇️</span>;

type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

async function resolveTauriInvoke(): Promise<TauriInvoke | null> {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: TauriInvoke };
      invoke?: TauriInvoke;
    };
  };

  if (typeof globalWindow.__TAURI__?.core?.invoke === "function") {
    return globalWindow.__TAURI__.core.invoke;
  }

  if (typeof globalWindow.__TAURI__?.invoke === "function") {
    return globalWindow.__TAURI__.invoke;
  }

  try {
    const core = await import("@tauri-apps/api/core");
    return typeof core.invoke === "function" ? core.invoke : null;
  } catch {
    return null;
  }
}

export function AutoAnnotatorPanel() {
  const [providers, setProviders] = useState<AutoAnnotatorProviderConfig[]>(
    createDefaultAutoAnnotatorConfig().providers
  );
  const [status, setStatus] = useState<"idle" | "running" | "success" | "error">("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved" | "error">("idle");
  const [saveMessage, setSaveMessage] = useState<string>(
    "Les fournisseurs sont enregistrés automatiquement sur cet appareil."
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const hasLoadedProvidersRef = useRef(false);

  useEffect(() => {
    let isActive = true;

    loadAutoAnnotatorConfig()
      .then((config) => {
        if (!isActive) {
          return;
        }
        setProviders(config.providers);
        setSaveStatus("saved");
      })
      .catch((error) => {
        if (!isActive) {
          return;
        }
        const reason =
          error instanceof Error ? error.message : "chargement de la configuration impossible";
        setSaveStatus("error");
        setSaveMessage(`Configuration locale indisponible: ${reason}`);
      })
      .finally(() => {
        if (isActive) {
          hasLoadedProvidersRef.current = true;
        }
      });

    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    if (!hasLoadedProvidersRef.current) {
      return;
    }

    let isActive = true;

    void persistAutoAnnotatorConfig({ providers })
      .then(() => {
        if (!isActive) {
          return;
        }
        setSaveStatus("saved");
        setSaveMessage("Configuration enregistrée automatiquement.");
      })
      .catch((error) => {
        if (!isActive) {
          return;
        }
        const reason =
          error instanceof Error ? error.message : "écriture automatique impossible";
        setSaveStatus("error");
        setSaveMessage(`Échec de l'enregistrement automatique: ${reason}`);
      });

    return () => {
      isActive = false;
    };
  }, [providers]);

  const addProvider = () => {
    setProviders([
      ...providers,
      {
        id: `fallback_${Date.now()}`,
        baseUrl: "",
        model: "",
        apiKey: "",
      }
    ]);
  };

  const removeProvider = (idToRemove: string) => {
    if (providers.length <= 1) return; // Garder au moins 1 fournisseur
    setProviders(providers.filter(p => p.id !== idToRemove));
  };

  const updateProvider = (id: string, field: keyof AutoAnnotatorProviderConfig, value: string) => {
    setProviders(providers.map(p => 
      p.id === id ? { ...p, [field]: value } : p
    ));
  };

  // Déplacer un fournisseur vers le HAUT
  const moveUp = (index: number) => {
    if (index === 0) return;
    const newProviders = [...providers];
    const temp = newProviders[index];
    newProviders[index] = newProviders[index - 1];
    newProviders[index - 1] = temp;
    setProviders(newProviders);
  };

  // Déplacer un fournisseur vers le BAS
  const moveDown = (index: number) => {
    if (index === providers.length - 1) return;
    const newProviders = [...providers];
    const temp = newProviders[index];
    newProviders[index] = newProviders[index + 1];
    newProviders[index + 1] = temp;
    setProviders(newProviders);
  };

  const startAnnotation = async () => {
    const normalizedProviders = providers.map((provider) => ({
      ...provider,
      baseUrl: provider.baseUrl.trim(),
      model: provider.model.trim(),
      apiKey: provider.apiKey.trim(),
    }));
    const runnableProviders = normalizedProviders.filter(
      (provider) => provider.baseUrl || provider.model || provider.apiKey
    );
    const incompleteProvider = runnableProviders.find((provider) => provider.model.length === 0);

    if (runnableProviders.length === 0) {
      const message = "Ajoute au moins un fournisseur avec un modèle avant de lancer l'annotation.";
      setStatus("error");
      setErrorMessage(message);
      setLogs((prev) => [...prev, message]);
      return;
    }

    if (incompleteProvider) {
      const message = "Chaque fournisseur utilisé doit avoir un modèle renseigné.";
      setStatus("error");
      setErrorMessage(message);
      setLogs((prev) => [...prev, message]);
      return;
    }

    setStatus("running");
    setErrorMessage(null);
    setLogs((prev) => [...prev, `Démarrage avec ${runnableProviders.length} fournisseur(s) configuré(s)...`]);

    const configPayload = {
      providers: runnableProviders.map(p => ({
        base_url: p.baseUrl,
        model: p.model,
        api_key: p.apiKey
      }))
    };
    
    try {
      const invoke = await resolveTauriInvoke();
      if (!invoke) {
        throw new Error("Tauri host unavailable");
      }

      const result = await invoke("run_auto_annotator", {
        config: configPayload
      }) as { success: boolean; message: string };
      
      setStatus(result.success ? "success" : "error");
      setErrorMessage(result.success ? null : result.message);
      setLogs((prev) => [...prev, result.message]);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setStatus("error");
      setErrorMessage(message);
      setLogs((prev) => [...prev, `Erreur fatale: ${message}`]);
    }
  };

  return (
    <Paper className="glass-card" sx={{ p: 3, mt: 3 }}>
      <Typography variant="h6" gutterBottom>
        🤖 Générateur de Dataset YOLO (Auto-Annotation)
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Configurez votre chaîne de fournisseurs Vision. Ajustez l'ordre de priorité avec les flèches. Si le premier échoue, le script basculera automatiquement sur le suivant.
      </Typography>
      <Alert severity={saveStatus === "error" ? "warning" : "info"} sx={{ mb: 2 }}>
        {saveMessage}
      </Alert>

      <Stack spacing={3}>
        <Box>
          {providers.map((provider, index) => (
            <Paper 
              key={provider.id} 
              variant="outlined" 
              sx={{ p: 2, mb: 2, borderColor: index === 0 ? "primary.main" : "divider" }}
            >
              <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                <Typography variant="subtitle2" color={index === 0 ? "primary.main" : "text.secondary"}>
                  {index === 0 ? "1. Fournisseur Principal" : `${index + 1}. Fallback de secours`}
                </Typography>
                
                <Stack direction="row" spacing={0.5}>
                  <IconButton size="small" onClick={() => moveUp(index)} disabled={index === 0} title="Monter en priorité">
                    <UpIcon />
                  </IconButton>
                  <IconButton size="small" onClick={() => moveDown(index)} disabled={index === providers.length - 1} title="Descendre en priorité">
                    <DownIcon />
                  </IconButton>
                  {providers.length > 1 && (
                    <IconButton size="small" onClick={() => removeProvider(provider.id)} color="error" title="Supprimer ce fournisseur" sx={{ ml: 2 }}>
                      <DeleteIcon />
                    </IconButton>
                  )}
                </Stack>
              </Stack>
              
              <Stack direction="row" spacing={2}>
                <TextField
                  label="Base URL (Optionnel si OpenAI)"
                  size="small"
                  fullWidth
                  value={provider.baseUrl}
                  onChange={(e) => updateProvider(provider.id, "baseUrl", e.target.value)}
                  placeholder="ex: https://api.groq.com/openai/v1"
                />
                <TextField
                  label="Modèle"
                  size="small"
                  fullWidth
                  value={provider.model}
                  onChange={(e) => updateProvider(provider.id, "model", e.target.value)}
                />
                <TextField
                  label="API Key"
                  size="small"
                  fullWidth
                  type="password"
                  value={provider.apiKey}
                  onChange={(e) => updateProvider(provider.id, "apiKey", e.target.value)}
                />
              </Stack>
            </Paper>
          ))}
          
          <Button 
            startIcon={<AddIcon />} 
            onClick={addProvider} 
            variant="text" 
            color="secondary"
            sx={{ mt: 1 }}
          >
            Ajouter un fournisseur de secours
          </Button>
        </Box>

          {status === "success" && <Alert severity="success">Annotation terminée avec succès !</Alert>}
          {status === "error" && (
            <Alert severity="error">
              {errorMessage ?? "Une erreur s'est produite lors de l'annotation."}
            </Alert>
          )}

        <Button
          variant="contained"
          color="primary"
          onClick={startAnnotation}
          disabled={status === "running"}
          size="large"
        >
          {status === "running" ? "⏳ Annotation en cascade en cours..." : "Lancer l'Auto-Annotation"}
        </Button>

        {logs.length > 0 && (
          <Box
            sx={{
              backgroundColor: "#1e1e1e",
              color: "#a6e22e",
              fontFamily: "monospace",
              p: 2,
              borderRadius: 1,
              maxHeight: "150px",
              overflowY: "auto",
              fontSize: "0.85rem"
            }}
          >
            {logs.map((log, i) => (
              <div key={i}>{log}</div>
            ))}
          </Box>
        )}
      </Stack>
    </Paper>
  );
}
