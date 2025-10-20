/**
 * @file receiver.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief Class for processing all discovered values
 * @version 0.1
 * @date 2025-10-15
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_RECEIVER_H_
#define WIKI_RECEIVER_H_

#include <vector>

#include "defines.h"

namespace wiki{

class Receiver{
public:
    void load_dict_list(const std::vector<std::string>& vals){
        dict_list = vals;
    }

    virtual void put_dictionary_value(const dict_key& d_key, const dict_key& key, const dict_val& val) = 0;
    virtual bool load() = 0;
    virtual bool save() = 0;

    /**
     * @brief
     *
     * @param dict
     * @return true
     * @return false
     */
    const bool is_dictionary(const std::string dict) const{
        for( auto it = dict_list.begin(); it != dict_list.end(); ++it ){
            if( *it == dict )
                return true;
        }
        return false;
    }

protected:
    std::vector<std::string> dict_list;
};

} //namespace wiki
#endif