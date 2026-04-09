import flam
from flam import utils
from flam import attrutils

@flam.register
class BlahFetcher(flam.ListFetcher, list_type='blah'):
    def fetch_into_file(self, movie_list_file: flam.MovieListFile) -> None:
        pass

@flam.register
class PlahPredicate(flam.Predicate, name_without_type='plah'):
    @classmethod
    def eat(cls, params: flam.EatParams, at: int) -> tuple[flam.Predicate, int]:
        return cls(), at

    def excrete(self, findable: flam.Findable) -> bool:
        return True

@flam.register
@attrutils.easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'blah',
    aliases_without_type = [],
    findable_type = flam.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = 999,
))
def _movie_blah_extractor(self: attrutils.EasyAttribute, movie: flam.Movie, mlf_movie: flam.MLFMovie) -> str:
    return 'blah'
