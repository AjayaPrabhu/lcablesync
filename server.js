const express = require("express");
const path = require("path");
const multer = require("multer");

const app = express();
const PORT = 3000;

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use("/static", express.static(path.join(__dirname, "static")));

// Serve frontend
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "index.html"));
});

// --- API ENDPOINTS ---

// Chat endpoint
app.post("/chat", (req, res) => {
  const { message } = req.body;
  res.json({ response: `🤖 Echo: ${message}` });
});

// Search PDFs
app.get("/search-pdf", (req, res) => {
  res.json([
    { name: "Example.pdf", path: "static/Example.pdf" }
  ]);
});

// Project summary
app.get("/search-summary", (req, res) => {
  res.json({
    project_count: 2,
    projects: ["Alpha", "Beta"]
  });
});

// Version summary
app.get("/search-versions", (req, res) => {
  res.json({
    version_count: 3,
    versions: [1, 2, 3]
  });
});

// File uploads
const upload = multer({ dest: "uploads/" });

app.post("/analyze-pdf", upload.single("file"), (req, res) => {
  res.json({ result: `✅ PDF uploaded: ${req.file.originalname}` });
});

app.post("/analyze-image", upload.single("file"), (req, res) => {
  res.json({ result: `✅ Image uploaded: ${req.file.originalname}` });
});

// Start server
app.listen(PORT, () => {
  console.log(`🚀 Server running at http://localhost:${PORT}`);
});
