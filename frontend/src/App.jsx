import ChatWidget from "./ChatWidget.jsx";

export default function App() {
  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        backgroundImage: "url('/dotstark-homepage.jpg')",
        backgroundSize: "cover",
        backgroundPosition: "center top",
        backgroundRepeat: "no-repeat",
      }}
    >
      {/* Floating chat widget */}
      <ChatWidget />
    </div>
  );
}
