# GoDSAT capstone assignment

`main.tex` is the student handout. It compiles to an eight-page PDF with pdfLaTeX and uses no external figures or bibliography files. Upload it to an Overleaf project and select pdfLaTeX. The handout adapts the supplied end-to-end neural optimization capstone to the current GoDSAT ground/NEXT study, rather than retaining its vehicle-loan project.

From the repository root:

```sh
mkdir -p tmp/pdfs output/pdf
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=tmp/pdfs assignments/godsat-capstone/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=tmp/pdfs assignments/godsat-capstone/main.tex
cp tmp/pdfs/main.pdf output/pdf/godsat-capstone-assignment.pdf
```

`instructor-notes.md` contains a short answer key and implementation/readiness notes. Do not include it in the student handout or student Overleaf project. `output/pdf/godsat-capstone-overleaf.zip` contains only `main.tex` and this README.

The assignment requires students to conduct the experiments. Creating the handout does not run the research campaign or implement its proposed compression/communication extensions. Instructors should distribute a complete pinned source snapshot before assigning exercises that rely on the simulation framework.

The linked Overleaf project was not accessible during authoring. No changes were made to that remote project. Source PDFs were read locally and remain unchanged.
