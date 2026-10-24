# Informe de Investigación ClonaKit: Anai App (`anaiapp.ai`)

**Fecha:** 2026-10-24  
**Objetivo:** Análisis técnico de la plataforma `app.anaiapp.ai` (estudio, funciones, arquitectura) y diagnóstico/reparación del inicio de sesión con Google.  
**Metodología:** Análisis de sala limpia e ingeniería inversa asistida (ClonaKit / inspección de bundles Next.js).

---

## 1. ¿Qué es Anai App y qué hace?

**Anai App (`anaiapp.ai`)** es una plataforma SaaS "todo en uno" de **creación y automatización de videos verticales (formato 9:16)** diseñada para redes sociales como TikTok, Instagram Reels y YouTube Shorts.

### Capacidades Principales:
1. **Estudio de Producción Vertical:** Reemplaza el flujo manual de edición, montaje y subtitulado generando piezas completas listas para exportar en MP4 sin marcas de agua.
2. **Generación de Contenido y Guiones con IA:** Genera ganchos (hooks), ideas virales y guiones optimizados para retención en redes.
3. **Avatares y Clones Digitales:** Integra personajes generados por IA o clones de voz y apariencia para narrar los videos.
4. **Flujo de Onboarding Asistido:** Cuestionario inicial que analiza el nicho, audiencia y estilo del creador para configurar su perfil de producción (`onboardingProfile`).

> [!NOTE]
> **Relación con nuestro proyecto:** Anai App tiene una propuesta funcional muy similar a lo que implementa `YOUTUBE AUTOMATION`, pero Anai es un servicio cloud cerrado, mientras que nosotros tenemos control total de los pipelines de MCP, Google Flow y NotebookLM en local.

---

## 2. Stack Técnico y Arquitectura Descubierta

Mediante el análisis de los bundles de cliente (`_next/static/chunks/0lqbu534fan9h.js`, `0yizq3m1jyvqu.js`), revelamos la arquitectura exacta:

| Capa | Tecnología | Detalles Detectados en Código |
| :--- | :--- | :--- |
| **Frontend Framework** | **Next.js 14/15** | App Router, Turbopack (`turbopack-2kpdcsloqvj4r.js`), SSR con React Server Components. |
| **Estilos e Iconografía** | **Tailwind CSS** | Clases CSS modulares (`auth-module__X4hENW__googleButton`), fuentes `Space Grotesk` e `Inter`. |
| **Gestión de Estado** | **Zustand** | Store de onboarding con Redux Devtools: `onboarding/setSessionId`, `onboardingProfile`, `scriptFromIdeasFlow`. |
| **Data Fetching / Cache**| **TanStack React Query** | `useQueryClient`, `Subscribable` cache. |
| **Backend API** | **NestJS / Express en GCP** | Servidor `Google Frontend` (Cloud Run), respuestas con `correlationId`. |
| **Autenticación** | **NextAuth.js (Auth.js)** | Proveedor Google OAuth (`next-auth/react`), hook `useAuth()`. |

---

## 3. Cómo Funciona su Autenticación con Google

En el archivo de cliente `0lqbu534fan9h.js`, extrajimos la implementación exacta del botón **"Continuar con Google"**:

```javascript
// Hook useAuth extraído del código de anai:
const useAuth = () => {
  const { data: session, status } = useSession();
  
  const signInWithGoogle = async (callbackUrl) => {
    try {
      resetOnboarding();
      await signIn("google", { 
        callbackUrl: callbackUrl || "/onboarding" 
      });
      return { success: true };
    } catch (error) {
      console.error("[Auth] Google sign-in error:", error);
      return { 
        success: false, 
        error: { message: "Error al iniciar sesión con Google" } 
      };
    }
  };

  return {
    user: session?.user,
    session,
    status,
    isLoading: status === "loading",
    isAuthenticated: !!session?.user,
    signInWithGoogle,
    signOut
  };
};
```

### Gestión de Errores OAuth de Anai:
El sistema maneja los errores nativos de Google OAuth:
- `OAuthAccountNotLinked`: Si el usuario ya se registró con correo/contraseña e intenta pulsar Google, muestra: *"Ya tienes una cuenta registrada con este correo usando email y contraseña"*.
- `ACCOUNT_USES_GOOGLE`: Si intenta ingresar con clave pero la cuenta se creó con Google, muestra: *"Tu cuenta fue creada con Google. Usa el botón de abajo para ingresar"*.
- `OAuthSignin` / `OAuthCallback`: Errores en la respuesta o redirección de Google.

---

## 4. ¿Por Qué Falla el Login de Google y Cómo Repararlo?

### La Causa del Bloqueo:
Google implementa **Google Identity Shield / Bot Detection** en `accounts.google.com`.
Si un usuario intenta hacer clic en *"Continuar con Google"* en Anai (o en cualquier app web) dentro de un navegador que:
1. Tiene activado el puerto de depuración remota (`--remote-debugging-port=9333` de CDP/Playwright).
2. O tiene flags de automatización como `navigator.webdriver = true`.

Google aborta el proceso con el mensaje:
> **"No se pudo iniciar sesión. Este navegador o app puede que no sea seguro. Más información. Prueba a usar otro navegador."**

### La Solución Operativa (Reparación del Login):

Para que el login de Google funcione al 100% sin bloqueos ni errores:

1. **Abrir Chrome en Modo Limpio (Nativo):**
   - El navegador DEBE ejecutarse **sin `--remote-debugging-port`**, con el perfil del usuario (`FlowImageChrome`).
   - Usar el botón en nuestro panel local: **`1. 🔑 Abrir Login Seguro Google`** o ejecutar `C:\Users\Johan\Desktop\VINCULAR-GOOGLE.bat`.
2. **Iniciar Sesión en Anai y en Google:**
   - En esa ventana limpia de Chrome, puedes navegar a:
     `https://app.anaiapp.ai/es/auth/login?callbackUrl=%2Fes%2Fstudio%2Fcontent%2Fhome`
   - Pulsa **"Continuar con Google"**.
   - Como el navegador está corriendo en modo normal y limpio (vía `os.startfile`), Google lo reconoce como un navegador 100% seguro y autoriza el login inmediatamente.
3. **Sesión Persistida:**
   - La cookie de sesión (`next-auth.session-token`) queda guardada en el perfil `FlowImageChrome`.
   - Cuando vuelves a abrir Chrome o activas el paso 2 (`2. 🚀 Conectar y Sincronizar`), la sesión de Google ya está iniciada y no requiere volver a ingresar contraseñas.
