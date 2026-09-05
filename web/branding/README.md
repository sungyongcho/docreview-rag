# DocReview RAG ASCII assets

`wordmark.txt` and `monogram.txt` are the canonical, checked-in text assets.
They use Glenn Chappell's upright **Small** font with FIGlet's full-width
horizontal layout. The wordmark is at most 78 columns; the `DR` monogram is
at most 13. Only trailing whitespace and the empty fifth font row are removed.
Interior spaces and backslashes are significant.

Font source: <https://github.com/patorjk/figlet.js/blob/master/fonts/Small.flf>
Preview tool: <https://patorjk.com/software/taag/>

The shell reads these files with `cat`; printing never needs FIGlet, Python,
Node, or network access. It chooses the full wordmark at 78 columns, the
monogram at 18 columns, and a plain product-name line below that width.

The Web imports the checked-in representation in `ascii.ts`.
`components/product-brand.test.tsx` compares both strings byte-for-byte
against the text files (excluding the final newline). When an asset changes,
update its corresponding string and run that parity test. Web surfaces use
the monogram by default and show the full wordmark only in spacious hero
containers; never stretch the lettering or reduce the full wordmark's font
to fit a narrow header.
