def getBookObject(id: int, source: str):
    if source.lower() == 'linovelib':
        from .lnd_linovelib import Book
        book = Book(id)
        return book

    elif source.lower() == 'wenku8':
        from .lnd_wenku8_download import Book
        return Book(id)


def main(id, source, download_all_volumes=True, **kwargs):
    book = getBookObject(id, source)
    return book.download(output_type='epub', download_all_volumes=download_all_volumes, kwargs=kwargs)
